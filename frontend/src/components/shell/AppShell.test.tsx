import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { NAV_ITEMS } from "../../app/router";
import { AsyncState } from "../ui/AsyncState";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Drawer } from "../ui/Drawer";
import { ToastProvider, useToast } from "../ui/ToastRegion";
import { renderAppAt } from "../../test/render";

beforeEach(() => {
  window.localStorage.clear();
  document.body.style.overflow = "";
});

afterEach(() => {
  vi.useRealTimers();
});

test("navigates through all command-center sections", async () => {
  const user = userEvent.setup();
  const { router } = renderAppAt("/");
  const navigation = screen.getByRole("navigation", { name: "主导航" });

  expect(navigation).toBeInTheDocument();
  expect(within(navigation).getAllByRole("link")).toHaveLength(11);

  await user.click(within(navigation).getByRole("link", { name: /项目空间/ }));

  expect(await screen.findByRole("heading", { name: "项目空间" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/projects");
});

test("keeps the exact command-center route and label contract", () => {
  expect(NAV_ITEMS.map(([path, label]) => [path, label])).toEqual([
    ["/", "研究总览"],
    ["/projects", "项目空间"],
    ["/literature", "文献库"],
    ["/experiments", "实验管理"],
    ["/assets", "数据资产"],
    ["/knowledge", "知识图谱"],
    ["/writing", "写作中心"],
    ["/reflections", "复盘洞察"],
    ["/agents", "智能体中心"],
    ["/approvals", "审批中心"],
    ["/settings", "系统设置"],
  ]);
});

test("marks only the current route as active", () => {
  renderAppAt("/knowledge");
  const navigation = screen.getByRole("navigation", { name: "主导航" });
  const currentLink = within(navigation).getByRole("link", { name: /知识图谱/ });

  expect(currentLink).toHaveAttribute("aria-current", "page");
  expect(within(navigation).getByRole("link", { name: /研究总览/ })).not.toHaveAttribute("aria-current");
});

test("persists the collapsed sidebar preference", async () => {
  const user = userEvent.setup();
  const firstRender = renderAppAt("/");

  await user.click(screen.getByRole("button", { name: "收起侧栏" }));

  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "collapsed");
  expect(window.localStorage.getItem("ai-researcher.sidebar.collapsed")).toBe("collapsed");

  firstRender.unmount();
  renderAppAt("/");
  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "collapsed");
});

test.each(["true", "false", "broken", "", "COLLAPSED"])(
  "defaults to expanded for malformed stored sidebar value %j",
  (storedValue) => {
    window.localStorage.setItem("ai-researcher.sidebar.collapsed", storedValue);
    renderAppAt("/");

    expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "expanded");
  },
);

test("restores only the validated collapsed sidebar value", () => {
  window.localStorage.setItem("ai-researcher.sidebar.collapsed", "collapsed");
  renderAppAt("/");

  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "collapsed");
});

test("defaults to expanded when the localStorage property is unavailable", () => {
  vi.spyOn(window, "localStorage", "get").mockReturnValue(undefined as unknown as Storage);

  expect(() => renderAppAt("/")).not.toThrow();
  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "expanded");
});

test("defaults to expanded when the localStorage property getter throws", () => {
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new DOMException("Access denied", "SecurityError");
  });

  expect(() => renderAppAt("/")).not.toThrow();
  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "expanded");
});

test("defaults to expanded when localStorage getItem throws", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("Access denied", "SecurityError");
  });

  expect(() => renderAppAt("/")).not.toThrow();
  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "expanded");
});

test("keeps sidebar interaction usable when localStorage setItem throws", async () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("Quota denied", "SecurityError");
  });
  const user = userEvent.setup();

  expect(() => renderAppAt("/")).not.toThrow();
  await user.click(screen.getByRole("button", { name: "收起侧栏" }));

  expect(screen.getByTestId("app-shell")).toHaveAttribute("data-sidebar", "collapsed");
});

function DrawerHarness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button">抽屉外按钮</button>
      <Drawer open={open} title="导航菜单" onClose={() => setOpen(false)}>
        <button type="button">抽屉内操作</button>
      </Drawer>
    </>
  );
}

test("drawer locks body scroll, takes focus, traps focus, and closes on Escape", async () => {
  const user = userEvent.setup();
  render(<DrawerHarness />);

  const dialog = screen.getByRole("dialog", { name: "导航菜单" });
  const closeButton = within(dialog).getByRole("button", { name: "关闭" });
  const actionButton = within(dialog).getByRole("button", { name: "抽屉内操作" });

  expect(document.body).toHaveStyle({ overflow: "hidden" });
  expect(closeButton).toHaveFocus();

  await user.tab({ shift: true });
  expect(actionButton).toHaveFocus();
  await user.keyboard("{Escape}");

  expect(screen.queryByRole("dialog", { name: "导航菜单" })).not.toBeInTheDocument();
  expect(document.body.style.overflow).toBe("");
});

function ClosedDrawerHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>打开抽屉</button>
      <Drawer open={open} title="详情抽屉" onClose={() => setOpen(false)}>
        <button type="button">抽屉动作</button>
      </Drawer>
    </>
  );
}

test("drawer backdrop closes and restores prior focus", async () => {
  const user = userEvent.setup();
  render(<ClosedDrawerHarness />);
  const trigger = screen.getByRole("button", { name: "打开抽屉" });

  await user.click(trigger);
  fireEvent.mouseDown(screen.getByTestId("drawer-backdrop"));

  expect(screen.queryByRole("dialog", { name: "详情抽屉" })).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
  expect(document.body.style.overflow).toBe("");
});

function DrawerUnmountHarness({ open }: { open: boolean }) {
  return (
    <>
      <button type="button">保留的触发器</button>
      <Drawer open={open} title="卸载抽屉" onClose={() => undefined}>
        <button type="button">抽屉动作</button>
      </Drawer>
    </>
  );
}

test("drawer unmount restores prior focus and original body overflow", () => {
  document.body.style.overflow = "clip";
  const view = render(<DrawerUnmountHarness open={false} />);
  const trigger = screen.getByRole("button", { name: "保留的触发器" });
  trigger.focus();
  view.rerender(<DrawerUnmountHarness open />);

  view.rerender(<DrawerUnmountHarness open={false} />);

  expect(document.body.style.overflow).toBe("clip");
  expect(trigger).toHaveFocus();
});

function NestedOverlayHarness() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setDrawerOpen(true)}>打开导航</button>
      <Drawer open={drawerOpen} title="导航抽屉" onClose={() => setDrawerOpen(false)}>
        <button type="button" onClick={() => setConfirmOpen(true)}>打开危险确认</button>
        <ConfirmDialog
          open={confirmOpen}
          title="危险确认"
          description="必须显式选择"
          confirmLabel="执行"
          danger
          onConfirm={() => undefined}
          onClose={() => setConfirmOpen(false)}
        />
      </Drawer>
    </>
  );
}

test("nested danger confirmation owns Escape and preserves the drawer lock", async () => {
  const user = userEvent.setup();
  render(<NestedOverlayHarness />);
  await user.click(screen.getByRole("button", { name: "打开导航" }));
  const confirmTrigger = screen.getByRole("button", { name: "打开危险确认" });
  await user.click(confirmTrigger);

  await user.keyboard("{Escape}");
  expect(screen.getByRole("dialog", { name: "危险确认" })).toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "导航抽屉" })).toBeInTheDocument();
  expect(document.body.style.overflow).toBe("hidden");

  await user.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("dialog", { name: "危险确认" })).not.toBeInTheDocument();
  expect(confirmTrigger).toHaveFocus();
  expect(document.body.style.overflow).toBe("hidden");

  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "导航抽屉" })).not.toBeInTheDocument();
  expect(document.body.style.overflow).toBe("");
});

function OverlayPair({ firstOpen, secondOpen }: { firstOpen: boolean; secondOpen: boolean }) {
  return (
    <>
      <button type="button">原始焦点</button>
      <Drawer open={firstOpen} title="第一层" onClose={() => undefined}>
        <button type="button">第一层动作</button>
      </Drawer>
      <Drawer open={secondOpen} title="第二层" onClose={() => undefined}>
        <button type="button">第二层动作</button>
      </Drawer>
    </>
  );
}

test("overlay cleanup is safe when lower and upper instances unmount out of order", () => {
  document.body.style.overflow = "clip";
  const view = render(<OverlayPair firstOpen={false} secondOpen={false} />);
  const originalFocus = screen.getByRole("button", { name: "原始焦点" });
  originalFocus.focus();

  view.rerender(<OverlayPair firstOpen secondOpen />);
  expect(within(screen.getByRole("dialog", { name: "第二层" })).getByRole("button", { name: "关闭" })).toHaveFocus();
  expect(document.body.style.overflow).toBe("hidden");

  view.rerender(<OverlayPair firstOpen={false} secondOpen />);
  expect(document.body.style.overflow).toBe("hidden");
  expect(within(screen.getByRole("dialog", { name: "第二层" })).getByRole("button", { name: "关闭" })).toHaveFocus();

  view.rerender(<OverlayPair firstOpen={false} secondOpen={false} />);
  expect(document.body.style.overflow).toBe("clip");
  expect(originalFocus).toHaveFocus();
});

test("multiple overlays use unique accessible title and description IDs", () => {
  render(
    <>
      <Drawer open title="唯一抽屉" onClose={() => undefined}><button type="button">内容</button></Drawer>
      <ConfirmDialog
        open
        title="唯一确认"
        description="唯一描述"
        confirmLabel="确认"
        onConfirm={() => undefined}
        onClose={() => undefined}
      />
    </>,
  );
  const drawer = screen.getByRole("dialog", { name: "唯一抽屉" });
  const confirm = screen.getByRole("dialog", { name: "唯一确认" });
  const titleIds = [drawer.getAttribute("aria-labelledby"), confirm.getAttribute("aria-labelledby")];

  expect(new Set(titleIds).size).toBe(2);
  expect(confirm.getAttribute("aria-describedby")).not.toBeNull();
  expect(confirm.getAttribute("aria-describedby")).not.toBe(confirm.getAttribute("aria-labelledby"));
});

test("danger confirmation ignores backdrop dismissal", async () => {
  const onClose = vi.fn();
  const onConfirm = vi.fn();
  const user = userEvent.setup();

  render(
    <>
      <button type="button">弹窗外按钮</button>
      <ConfirmDialog
        open
        title="取消运行"
        description="此操作不能自动撤销。"
        confirmLabel="确认取消"
        danger
        onConfirm={onConfirm}
        onClose={onClose}
      />
    </>,
  );

  expect(document.body).toHaveStyle({ overflow: "hidden" });
  expect(screen.getByRole("button", { name: "取消" })).toHaveFocus();
  await user.tab({ shift: true });
  expect(screen.getByRole("button", { name: "确认取消" })).toHaveFocus();

  await user.click(screen.getByTestId("confirm-dialog-backdrop"));
  expect(onClose).not.toHaveBeenCalled();

  await user.keyboard("{Escape}");
  expect(onClose).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "确认取消" }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
});

function NormalDialogHarness() {
  const [open, setOpen] = useState(true);
  return (
    <ConfirmDialog
      open={open}
      title="普通确认"
      description="可以关闭"
      confirmLabel="确认"
      onConfirm={() => undefined}
      onClose={() => setOpen(false)}
    />
  );
}

test("normal confirmation dismisses from backdrop and Escape", async () => {
  const user = userEvent.setup();
  const first = render(<NormalDialogHarness />);
  fireEvent.mouseDown(screen.getByTestId("confirm-dialog-backdrop"));
  expect(screen.queryByRole("dialog", { name: "普通确认" })).not.toBeInTheDocument();
  first.unmount();

  render(<NormalDialogHarness />);
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "普通确认" })).not.toBeInTheDocument();
});

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

test("successful async confirmation closes exactly once", async () => {
  const request = deferred();
  const onClose = vi.fn();
  const user = userEvent.setup();
  render(
    <ConfirmDialog open title="提交" description="等待完成" confirmLabel="提交" onConfirm={() => request.promise} onClose={onClose} />,
  );

  await user.click(screen.getByRole("button", { name: "提交" }));
  await act(async () => request.resolve());

  expect(onClose).toHaveBeenCalledTimes(1);
});

test("rejected async confirmation stays open, announces the error, and restores usability", async () => {
  const request = deferred();
  const onClose = vi.fn();
  const user = userEvent.setup();
  render(
    <ConfirmDialog open title="提交" description="等待完成" confirmLabel="提交" onConfirm={() => request.promise} onClose={onClose} />,
  );
  await user.click(screen.getByRole("button", { name: "提交" }));

  await act(async () => request.reject(new Error("服务拒绝操作")));

  expect(screen.getByRole("dialog", { name: "提交" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("服务拒绝操作");
  expect(screen.getByRole("button", { name: "提交" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "取消" })).toBeEnabled();
  expect(onClose).not.toHaveBeenCalled();
});

test("async confirmation uses a safe fallback for an unusable rejection message", async () => {
  const user = userEvent.setup();
  render(
    <ConfirmDialog
      open
      title="提交"
      description="等待完成"
      confirmLabel="提交"
      onConfirm={() => Promise.reject({ get message() { throw new Error("unsafe getter"); } })}
      onClose={() => undefined}
    />,
  );

  await user.click(screen.getByRole("button", { name: "提交" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("操作失败，请重试。");
});

test("pending async confirmation blocks dismissal and makes both actions unavailable", async () => {
  const request = deferred();
  const onClose = vi.fn();
  const user = userEvent.setup();
  render(
    <ConfirmDialog open title="提交" description="等待完成" confirmLabel="提交" onConfirm={() => request.promise} onClose={onClose} />,
  );
  await user.click(screen.getByRole("button", { name: "提交" }));

  expect(screen.getByRole("button", { name: "处理中…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "取消" })).toHaveAttribute("aria-disabled", "true");
  fireEvent.mouseDown(screen.getByTestId("confirm-dialog-backdrop"));
  await user.keyboard("{Escape}");
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(onClose).not.toHaveBeenCalled();

  await act(async () => request.resolve());
});

test("pending async confirmation keeps focus inside for Tab and Shift+Tab", async () => {
  const request = deferred();
  const user = userEvent.setup();
  render(
    <ConfirmDialog open title="提交" description="等待完成" confirmLabel="提交" onConfirm={() => request.promise} onClose={() => undefined} />,
  );

  await user.click(screen.getByRole("button", { name: "提交" }));
  const safePendingControl = screen.getByRole("button", { name: "取消" });

  expect(safePendingControl).toHaveAttribute("aria-disabled", "true");
  expect(safePendingControl).not.toBeDisabled();
  expect(safePendingControl).toHaveFocus();

  await user.tab();
  expect(safePendingControl).toHaveFocus();
  await user.tab({ shift: true });
  expect(safePendingControl).toHaveFocus();

  await act(async () => request.resolve());
});

test("double confirmation submits only once", () => {
  const request = deferred();
  const onConfirm = vi.fn(() => request.promise);
  render(
    <ConfirmDialog open title="提交" description="等待完成" confirmLabel="提交" onConfirm={onConfirm} onClose={() => undefined} />,
  );
  const submit = screen.getByRole("button", { name: "提交" });

  fireEvent.click(submit);
  fireEvent.click(submit);

  expect(onConfirm).toHaveBeenCalledTimes(1);
});

test("async settlement after unmount has no close side effect", async () => {
  const request = deferred();
  const onClose = vi.fn();
  const user = userEvent.setup();
  const view = render(
    <ConfirmDialog open title="提交" description="等待完成" confirmLabel="提交" onConfirm={() => request.promise} onClose={onClose} />,
  );
  await user.click(screen.getByRole("button", { name: "提交" }));
  view.unmount();

  await act(async () => request.resolve());

  expect(onClose).not.toHaveBeenCalled();
});

test("header placeholders are explicitly unavailable and non-interactive", () => {
  renderAppAt("/");

  expect(screen.getByRole("button", { name: "通知（暂不可用）" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "帮助（暂不可用）" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "本地研究者（暂不可用）" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "通知（暂不可用）" })).toHaveAttribute("title", "暂不可用");
});

test("async error state retries the real operation", async () => {
  const onRetry = vi.fn();
  const user = userEvent.setup();

  render(
    <AsyncState loading={false} error={new Error("服务不可用")} empty={false} onRetry={onRetry}>
      <p>真实内容</p>
    </AsyncState>,
  );

  expect(screen.getByRole("alert")).toHaveTextContent("服务不可用");
  expect(screen.queryByText("真实内容")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "重试" }));
  expect(onRetry).toHaveBeenCalledTimes(1);
});

function ToastHarness() {
  const { notify } = useToast();
  return <button type="button" onClick={() => notify({ tone: "success", message: "研究已创建" })}>发送通知</button>;
}

test("toast announcements use a polite live region", async () => {
  const user = userEvent.setup();
  render(<ToastProvider><ToastHarness /></ToastProvider>);

  const region = screen.getByRole("status");
  expect(region).toHaveAttribute("aria-live", "polite");

  await user.click(screen.getByRole("button", { name: "发送通知" }));
  await waitFor(() => expect(region).toHaveTextContent("研究已创建"));
});

function BurstToastHarness() {
  const { notify } = useToast();
  return (
    <button
      type="button"
      onClick={() => {
        for (let index = 1; index <= 6; index += 1) {
          notify({ tone: "info", message: `通知 ${index}` });
        }
      }}
    >
      连续通知
    </button>
  );
}

test("keeps repeated toast IDs independent and offers an accessible manual dismiss", async () => {
  const user = userEvent.setup();
  render(<ToastProvider><ToastHarness /></ToastProvider>);

  const trigger = screen.getByRole("button", { name: "发送通知" });
  await user.click(trigger);
  await user.click(trigger);
  await user.click(trigger);
  expect(screen.getAllByText("研究已创建")).toHaveLength(3);

  const dismissButtons = screen.getAllByRole("button", { name: "关闭通知：研究已创建" });
  expect(dismissButtons).toHaveLength(3);
  await user.click(dismissButtons[0]!);
  expect(screen.getAllByText("研究已创建")).toHaveLength(2);
});

test("bounds the shared toast queue to the four newest messages", async () => {
  const user = userEvent.setup();
  render(<ToastProvider><BurstToastHarness /></ToastProvider>);

  await user.click(screen.getByRole("button", { name: "连续通知" }));

  expect(screen.queryByText("通知 1")).not.toBeInTheDocument();
  expect(screen.queryByText("通知 2")).not.toBeInTheDocument();
  expect(screen.getByText("通知 3")).toBeInTheDocument();
  expect(screen.getByText("通知 6")).toBeInTheDocument();
});

test("automatically removes a toast after five seconds", () => {
  vi.useFakeTimers();
  render(<ToastProvider><ToastHarness /></ToastProvider>);
  fireEvent.click(screen.getByRole("button", { name: "发送通知" }));
  expect(screen.getByText("研究已创建")).toBeInTheDocument();

  act(() => { vi.advanceTimersByTime(5_000); });

  expect(screen.queryByText("研究已创建")).not.toBeInTheDocument();
});

test("clears every pending toast timer when the provider unmounts", () => {
  vi.useFakeTimers();
  const view = render(<ToastProvider><BurstToastHarness /></ToastProvider>);
  fireEvent.click(screen.getByRole("button", { name: "连续通知" }));
  expect(vi.getTimerCount()).toBe(4);

  view.unmount();

  expect(vi.getTimerCount()).toBe(0);
});
