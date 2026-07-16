import { Check, X, CircleDashed, type LucideIcon } from "lucide-react";
import type { Status } from "../api";

export interface StatusStyle {
  /** short label for a single criterion */
  leafLabel: string;
  /** headline for the overall branch verdict */
  verdictLabel: string;
  icon: LucideIcon;
  /** foreground (icon + accent text) */
  fg: string;
  /** icon chip background */
  chipBg: string;
  /** soft tint used for the verdict banner */
  bannerBg: string;
  bannerBorder: string;
  dot: string;
}

export const STATUS: Record<Status, StatusStyle> = {
  MET: {
    leafLabel: "Met",
    verdictLabel: "Meets medical necessity",
    icon: Check,
    fg: "text-mint-deep",
    chipBg: "bg-mint",
    bannerBg: "bg-mint-tint",
    bannerBorder: "border-mint/40",
    dot: "bg-mint",
  },
  NOT_MET: {
    leafLabel: "Not met",
    verdictLabel: "Does not meet criteria",
    icon: X,
    fg: "text-danger",
    chipBg: "bg-danger",
    bannerBg: "bg-danger-tint",
    bannerBorder: "border-danger/30",
    dot: "bg-danger",
  },
  INSUFFICIENT_EVIDENCE: {
    leafLabel: "Missing evidence",
    verdictLabel: "Incomplete — evidence needed",
    icon: CircleDashed,
    fg: "text-warn",
    chipBg: "bg-warn",
    bannerBg: "bg-warn-tint",
    bannerBorder: "border-warn/30",
    dot: "bg-warn",
  },
};

/** Flatten a criteria tree to its evaluated leaves (and unmappable nodes). */
export function leavesOf<T extends { kind: string; children: T[] }>(node: T): T[] {
  if (node.kind === "leaf" || node.kind === "unmappable") return [node];
  return node.children.flatMap(leavesOf);
}
