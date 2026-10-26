import Image from "next/image";

/** 队徽；没有图片时显示文字标记。旁边已有队名时传 decorative，读屏不重复念。 */
export function TeamCrest({
  crest,
  short,
  name,
  decorative = false,
  className = "",
}: {
  crest: string | null;
  short: string;
  name: string;
  decorative?: boolean;
  className?: string;
}) {
  if (!crest) {
    return (
      <span
        className={"team-badge " + className}
        aria-hidden={decorative || undefined}
        aria-label={decorative ? undefined : name}
        role={decorative ? undefined : "img"}
      >
        {short}
      </span>
    );
  }
  return (
    <Image
      src={crest}
      alt={decorative ? "" : name + "队徽"}
      width={46}
      height={46}
      unoptimized
      className={"team-crest " + className}
    />
  );
}
