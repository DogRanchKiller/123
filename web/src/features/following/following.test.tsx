import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  FollowingProvider,
  FollowButton,
  FOLLOWING_KEY,
} from "./following.client";
import { FollowingList } from "./following-list.client";

function Watch() {
  return (
    <FollowingProvider>
      <FollowButton id="demo-test" label="测试比赛" />
    </FollowingProvider>
  );
}

describe("手动关注", () => {
  it("关注、重挂载恢复、取消关注", async () => {
    const user = userEvent.setup();
    const first = render(<Watch />);
    await user.click(screen.getByRole("button", { name: "关注测试比赛" }));
    expect(JSON.parse(localStorage.getItem(FOLLOWING_KEY)!)).toEqual([
      "demo-test",
    ]);
    first.unmount();
    render(<Watch />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "取消关注测试比赛" }),
      ).toHaveAttribute("aria-pressed", "true"),
    );
    await user.click(screen.getByRole("button", { name: "取消关注测试比赛" }));
    expect(JSON.parse(localStorage.getItem(FOLLOWING_KEY)!)).toEqual([]);
  });

  it("已有关注不会被首次空状态覆盖", async () => {
    localStorage.setItem(
      FOLLOWING_KEY,
      JSON.stringify(["demo-test", "another"]),
    );
    render(<Watch />);
    await screen.findByRole("button", { name: "取消关注测试比赛" });
    expect(JSON.parse(localStorage.getItem(FOLLOWING_KEY)!)).toEqual([
      "demo-test",
      "another",
    ]);
  });

  it("关注的比赛不在当前数据里时提示场数，不悄悄消失", async () => {
    localStorage.setItem(FOLLOWING_KEY, JSON.stringify(["gone-1", "gone-2"]));
    render(
      <FollowingProvider>
        <FollowingList matches={[]} />
      </FollowingProvider>,
    );
    expect(await screen.findByRole("note")).toHaveTextContent("另有 2 场关注");
    expect(screen.getByText("当前没有可显示的关注")).toBeInTheDocument();
  });

  it("存储不可用仍能临时关注并提示", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const user = userEvent.setup();
    render(<Watch />);
    await user.click(screen.getByRole("button", { name: "关注测试比赛" }));
    expect(
      screen.getByRole("button", { name: "取消关注测试比赛" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status")).toHaveTextContent("无法保存");
  });
});
