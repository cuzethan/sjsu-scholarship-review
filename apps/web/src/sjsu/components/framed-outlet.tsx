import type { ReactNode } from "react";
import { FrameCross } from "@/sjsu/components/icons/frame-cross";

// centered content column with border-x frame lines and corner crosses.
// (ascii-dot gutter background removed.)
export function FramedOutlet({ children, bleed }: { children: ReactNode; bleed?: boolean }) {
  // some pages (e.g. the rubric pdf split-view) need the full outlet width - skip
  // the centered frame and padding entirely.
  if (bleed) return <div className="h-full w-full overflow-hidden">{children}</div>;
  return (
    <div className="relative h-full">
      {/* frame + crosses stay pinned; only the inner div scrolls */}
      <div className="relative z-[1] mx-auto flex h-full w-full max-w-5xl flex-col border-x bg-background">
        <FrameCross className="-left-[11px] -top-[11px]" />
        <FrameCross className="-right-[11px] -top-[11px]" />
        <FrameCross className="-left-[11px] -bottom-[11px]" />
        <FrameCross className="-right-[11px] -bottom-[11px]" />
        <div className="flex-1 overflow-auto overscroll-none px-8 py-10">{children}</div>
      </div>
    </div>
  );
}
