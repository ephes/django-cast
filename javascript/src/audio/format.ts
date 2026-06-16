// Time formatting helpers for the transport UI.

export function formatTime(totalSeconds: number): string {
  let value = totalSeconds;
  if (!Number.isFinite(value) || value < 0) {
    value = 0;
  }
  const whole = Math.floor(value);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const seconds = whole % 60;
  const ss = String(seconds).padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${ss}`;
  }
  return `${minutes}:${ss}`;
}

// A spoken, screen-reader-friendly rendering used for the range `aria-valuetext`.
export function spokenTime(totalSeconds: number): string {
  let value = totalSeconds;
  if (!Number.isFinite(value) || value < 0) {
    value = 0;
  }
  const whole = Math.floor(value);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const seconds = whole % 60;
  const parts: string[] = [];
  if (hours > 0) {
    parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
  }
  if (minutes > 0) {
    parts.push(`${minutes} minute${minutes === 1 ? "" : "s"}`);
  }
  parts.push(`${seconds} second${seconds === 1 ? "" : "s"}`);
  return parts.join(" ");
}
