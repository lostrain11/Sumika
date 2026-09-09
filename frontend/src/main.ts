import "../styles.css";
import "./scene-layout.css";
import "./a-plus-layout.css";
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
import { NAV_ITEMS } from "./scene-shell.js";

export const pageRoutes = NAV_ITEMS.map(([page]) => page);

export type PageRoute = (typeof pageRoutes)[number];
