import type { CSSProperties } from "react";
import ai from "../assets/icons/ai.svg";
import asset from "../assets/icons/asset.svg";
import report from "../assets/icons/report.svg";
import signal from "../assets/icons/signal.svg";
import vibration from "../assets/icons/vibration.svg";
import temperature from "../assets/icons/temperature.svg";
import check from "../assets/icons/check.svg";
import arrow from "../assets/icons/arrow.svg";
import update from "../assets/icons/update.svg";

const icons = { ai, asset, report, signal, vibration, temperature, check, arrow, update };

export function BrandIcon({ name, className = "" }: { name: keyof typeof icons; className?: string }) {
  return <span aria-hidden="true" className={`brand-icon ${className}`} style={{ "--icon-url": `url("${icons[name]}")` } as CSSProperties} />;
}
