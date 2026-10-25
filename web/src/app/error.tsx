"use client";

import { SiteFrame } from "./site-frame";
import { ReadError } from "@/components/route-feedback";

export default function ErrorPage() {
  return (
    <SiteFrame><ReadError /></SiteFrame>
  );
}
