// One source of truth for version labels in new React components.
// Updating frontend/package.json and rebuilding updates this automatically.
import packageInfo from '../package.json';
export const APP_VERSION = packageInfo.version;
export const APP_VERSION_LABEL = `LocalLens v${APP_VERSION}`;
