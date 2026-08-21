import { render, screen, within } from "@testing-library/react";
import { App } from "./App";

test("renders the research command center root", () => {
  render(<App />);
  expect(within(screen.getByRole("banner")).getByText("研究总览")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "研究总览", level: 1 })).toBeInTheDocument();
});
