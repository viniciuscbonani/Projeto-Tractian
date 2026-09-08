export function StatusPill({ value, label }: { value: string | null | undefined; label?: string }) {
  const normalized = value ?? "unknown";
  const className = normalized.toLowerCase().replaceAll(/[^a-z0-9_-]/g, "-");
  return <span className={`status status--${className}`}>{label ?? normalized.replaceAll("_", " ")}</span>;
}
