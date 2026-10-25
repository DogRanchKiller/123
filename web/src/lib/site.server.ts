import "server-only";
import type { Metadata } from "next";

export const siteUrl = new URL(process.env.SITE_URL ?? "http://localhost:3000");

export function pageMetadata(
  title: string,
  description: string,
  path: string,
): Metadata {
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      title,
      description,
      url: path,
      locale: "zh_CN",
      type: "website",
    },
  };
}
