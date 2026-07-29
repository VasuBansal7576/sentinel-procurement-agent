import { render, screen } from "@testing-library/react";

import { App } from "./App";

describe("App", () => {
  it("identifies the workbench and its readiness state", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: /procurement operations/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Foundation active");
  });
});
