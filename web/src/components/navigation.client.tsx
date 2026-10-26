"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Icon } from "@/components/icon";

const navigation = [
  { href: "/", label: "首页", icon: "ball" },
  { href: "/predictions", label: "比赛预测", icon: "grid" },
  { href: "/following", label: "我的关注", icon: "star" },
  { href: "/review", label: "赛后成绩单", icon: "chart" },
] as const;

export function Navigation() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className="button menu-button"
        aria-expanded={open}
        aria-controls="main-navigation"
        aria-label={open ? "收起导航" : "展开导航"}
        onClick={() => setOpen(!open)}
      >
        <Icon name="menu" />
      </button>
      <nav
        className="navigation"
        id="main-navigation"
        data-open={open}
        aria-label="主导航"
      >
        {navigation.map(({ href, label, icon }) => (
          <Link
            key={href}
            href={href}
            scroll={href === "/predictions" ? false : undefined}
            className="nav-link"
            aria-current={(href === "/" ? pathname === "/" : pathname.startsWith(href)) ? "page" : undefined}
            onClick={() => setOpen(false)}
          >
            <Icon name={icon} />
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
