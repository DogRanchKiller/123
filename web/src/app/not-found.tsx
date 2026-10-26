import { SiteFrame } from "./site-frame";
import { MissingPage } from "@/components/route-feedback";

export default function NotFound() {
  return (
    <SiteFrame><MissingPage /></SiteFrame>
  );
}
