import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Predictions } from "./predictions.client";
import { FollowingProvider } from "@/features/following";

it("没有推荐时不强行选择比赛", () => {
  render(
    <FollowingProvider>
      <Predictions matches={[]} source={{ mode: "demo" }} />
    </FollowingProvider>,
  );
  expect(screen.getByRole("heading", { name: "暂无推荐" })).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: "没有符合筛选的比赛" }),
  ).toBeInTheDocument();
});
