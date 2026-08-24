import "../styles.css";
import "../main.js";

/**
 * Vue migration boundary.
 *
 * The browser `main.js` shell intentionally mirrors the page structure here
 * while the project evaluates the Vue/Tauri migration. Importing it from the
 * Vite entry keeps the Tauri production bundle equivalent to the browser
 * preview; future Vue pages can replace this bridge without changing the
 * routes, event contracts, or runtime renderer boundary.
 */
export const pageRoutes = [
  "Chat",
  "Characters",
  "Modules",
  "Tasks",
  "History",
  "Notifications",
  "Settings",
  "Developer",
  "Guide",
] as const;

export type PageRoute = (typeof pageRoutes)[number];
