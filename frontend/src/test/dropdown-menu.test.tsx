import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

function MultiSelectHarness() {
  const ALL = ["serie_a", "premier_league", "la_liga"];
  const [selected, setSelected] = useState<string[]>([]);
  const toggle = (value: string) =>
    setSelected((cur) =>
      cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value],
    );
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">
          {selected.length === 0 ? "All leagues" : `${selected.length} selected`}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {ALL.map((v) => (
          <DropdownMenuCheckboxItem
            key={v}
            checked={selected.includes(v)}
            onCheckedChange={() => toggle(v)}
          >
            {v}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

describe("DropdownMenuCheckboxItem", () => {
  it("stays open across multiple selections so the user can toggle several items", async () => {
    const user = userEvent.setup();
    render(<MultiSelectHarness />);

    await user.click(screen.getByRole("button", { name: /all leagues/i }));

    const serie = await screen.findByRole("menuitemcheckbox", { name: "serie_a" });
    await user.click(serie);
    // Menu stays open; toggling another item is possible without reopening.
    const premier = screen.getByRole("menuitemcheckbox", { name: "premier_league" });
    expect(premier).toBeVisible();
    await user.click(premier);

    expect(
      screen.getByRole("menuitemcheckbox", { name: "serie_a" }),
    ).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByRole("menuitemcheckbox", { name: "premier_league" }),
    ).toHaveAttribute("aria-checked", "true");
    // Third (un-clicked) item should still be in the DOM — proves the menu
    // did not close and remount between clicks.
    expect(
      screen.getByRole("menuitemcheckbox", { name: "la_liga" }),
    ).toHaveAttribute("aria-checked", "false");
  });
});
