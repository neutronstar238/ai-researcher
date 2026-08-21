import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiClient } from "../../lib/api/client";
import { healthFixture } from "../../test/fixtures";
import { renderAppAt } from "../../test/render";

vi.mock("../../lib/api/client", () => ({ apiClient: { health: vi.fn() } }));

const THEME_KEY = "ai-researcher-theme";

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
  vi.mocked(apiClient.health).mockResolvedValue(healthFixture());
});

afterEach(() => {
  delete document.documentElement.dataset.theme;
});

test("renders every backend health boolean exactly with service and deployment facts", async () => {
  vi.mocked(apiClient.health).mockResolvedValue(healthFixture({
    authentication_enabled: true,
    formal_experiment_enabled: false,
    result_paper_enabled: true,
    self_evolution_execution_enabled: false,
    self_evolution_service_configured: true,
    automatic_skill_activation_enabled: false,
    batch_execution_configured: true,
  }));
  renderAppAt("/settings");

  const facts = await screen.findByRole("table", { name: "服务能力" });
  expect(within(facts).getByRole("row", { name: "身份认证 是" })).toBeInTheDocument();
  expect(within(facts).getByRole("row", { name: "正式实验 否" })).toBeInTheDocument();
  expect(within(facts).getByRole("row", { name: "结果论文 是" })).toBeInTheDocument();
  expect(within(facts).getByRole("row", { name: "自进化执行 否" })).toBeInTheDocument();
  expect(within(facts).getByRole("row", { name: "自进化服务配置 是" })).toBeInTheDocument();
  expect(within(facts).getByRole("row", { name: "自动 Skill 激活 否" })).toBeInTheDocument();
  expect(within(facts).getByRole("row", { name: "批量执行配置 是" })).toBeInTheDocument();
  expect(screen.getByText("autoresearch-local-api")).toBeInTheDocument();
  expect(screen.getByText("local_single_user")).toBeInTheDocument();
});

test("shows health errors and retries", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.health)
    .mockRejectedValueOnce(new Error("健康接口失败"))
    .mockResolvedValueOnce(healthFixture());
  renderAppAt("/settings");

  expect(await screen.findByRole("alert")).toHaveTextContent("健康接口失败");
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByRole("table", { name: "服务能力" })).toBeInTheDocument();
});

test("offers exactly light, dark, and system and persists only the validated theme key", async () => {
  const user = userEvent.setup();
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  renderAppAt("/settings");

  const group = screen.getByRole("radiogroup", { name: "主题" });
  expect(within(group).getAllByRole("radio").map((radio) => radio.getAttribute("value"))).toEqual(["light", "dark", "system"]);
  await user.click(within(group).getByRole("radio", { name: "深色" }));
  expect(window.localStorage.getItem(THEME_KEY)).toBe("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(setItem).toHaveBeenCalledWith(THEME_KEY, "dark");
});

test.each(["", "broken", "DARK", "auto", "null"])("rejects malformed stored theme %j", (stored) => {
  window.localStorage.setItem(THEME_KEY, stored);
  renderAppAt("/settings");
  expect(screen.getByRole("radio", { name: "跟随系统" })).toBeChecked();
});

test("applies a stored theme from the app shell on direct non-settings navigation", () => {
  window.localStorage.setItem(THEME_KEY, "dark");
  renderAppAt("/knowledge");
  expect(document.documentElement.dataset.theme).toBe("dark");
});

test("keeps the core settings route operable on a direct dark-theme load", async () => {
  window.localStorage.setItem(THEME_KEY, "dark");
  renderAppAt("/settings");

  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(screen.getByRole("heading", { name: "系统设置", level: 1 })).toBeInTheDocument();
  expect(screen.getByRole("radiogroup", { name: "主题" })).toBeInTheDocument();
  expect(await screen.findByRole("table", { name: "服务能力" })).toBeInTheDocument();
});

test("keeps theme controls usable when storage property, reads, or writes fail", async () => {
  const user = userEvent.setup();
  vi.spyOn(Storage.prototype, "getItem").mockImplementation((key) => {
    if (key === THEME_KEY) throw new DOMException("read denied", "SecurityError");
    return null;
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation((key) => {
    if (key === THEME_KEY) throw new DOMException("write denied", "QuotaExceededError");
  });

  expect(() => renderAppAt("/settings")).not.toThrow();
  await user.click(screen.getByRole("radio", { name: "浅色" }));
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("falls back safely when the localStorage property is unavailable", () => {
  vi.spyOn(window, "localStorage", "get").mockReturnValue(undefined as unknown as Storage);
  expect(() => renderAppAt("/settings")).not.toThrow();
  expect(screen.getByRole("radio", { name: "跟随系统" })).toBeChecked();
});

test("system theme follows media changes and removes its listener on unmount", async () => {
  let listener: ((event: MediaQueryListEvent) => void) | undefined;
  const addEventListener = vi.fn((_type: string, next: (event: MediaQueryListEvent) => void) => { listener = next; });
  const removeEventListener = vi.fn();
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: false,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener,
    removeEventListener,
    dispatchEvent: vi.fn(),
  })));
  window.localStorage.setItem(THEME_KEY, "system");
  const rendered = renderAppAt("/settings");
  expect(document.documentElement.dataset.theme).toBe("light");

  await act(async () => listener?.({ matches: true } as MediaQueryListEvent));
  expect(document.documentElement.dataset.theme).toBe("dark");
  rendered.unmount();
  expect(removeEventListener).toHaveBeenCalledWith("change", listener);
});

test("system mode remains usable when matchMedia is unavailable", () => {
  vi.stubGlobal("matchMedia", undefined);
  window.localStorage.setItem(THEME_KEY, "system");
  expect(() => renderAppAt("/settings")).not.toThrow();
  expect(document.documentElement.dataset.theme).toBe("light");
});
