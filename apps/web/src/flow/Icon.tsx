import type { IconName } from "./model";

// The site's status icons (apps/site sprite), inline so the map draws the same on any page or in the app.
const PATHS: Record<IconName, JSX.Element> = {
  replaced: <><path d="M2.5 5.5h9.5M9.5 3l2.5 2.5L9.5 8" /><path d="M13.5 10.5H4M6.5 8L4 10.5 6.5 13" /></>,
  contradicts: <><circle cx="8" cy="8" r="5.75" /><path d="M5.75 5.75l4.5 4.5M10.25 5.75l-4.5 4.5" /></>,
  partly: <><circle cx="8" cy="8" r="5.75" /><path className="fx-icon-fill" d="M8 2.25v11.5a5.75 5.75 0 0 0 0-11.5z" /></>,
  supports: <><circle cx="8" cy="8" r="5.75" /><path d="M5.25 8.25l1.9 1.9 3.6-4.1" /></>,
  review: <><path d="M8 2.25l6 11H2z" /><path d="M8 6.75v3" /><path d="M8 11.6v.1" /></>,
  inforce: <><rect x="2.75" y="2.75" width="10.5" height="10.5" rx="2" /><path d="M5.25 8.25l1.9 1.9 3.6-4.1" /></>,
  none: <><circle cx="8" cy="8" r="5.75" /><path d="M5.5 8h5" /></>,
  evidence: <><path d="M4 2.5h5.5L12 5v8.5H4z" /><path d="M6.25 8h3.5M6.25 10.5h3.5" /></>,
};

export function Icon({ name }: { name: IconName }) {
  return <svg className="fx-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">{PATHS[name]}</svg>;
}
