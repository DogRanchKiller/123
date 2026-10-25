import Link from "next/link";
import { EmptyState } from "@/components/presentation";

export default function NotFound() {
  return (
    <>
      <EmptyState
        title="找不到这场比赛或页面"
        description="请检查地址，或返回比赛列表。未知场次不会被当作数据读取故障。"
      />
      <Link href="/predictions" className="text-link mt-5">
        返回比赛列表 →
      </Link>
    </>
  );
}
