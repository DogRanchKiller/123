import { SiteFrame } from "../site-frame";

export default function BrowseLayout({ children }: { children: React.ReactNode }) {
  return <SiteFrame>{children}</SiteFrame>;
}
