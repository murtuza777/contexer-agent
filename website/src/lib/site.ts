// Set SITE_URL when deploying (for example https://contexer.example). Social cards and the
// sitemap use it for absolute URLs.
export const SITE_URL = process.env.SITE_URL ?? "http://localhost:3000";

export const REPO_URL = "https://github.com/murtuza777/contexer-agent";
export const DOCS_URL = `${REPO_URL}#readme`;
export const RESULTS_URL = `${REPO_URL}/blob/main/contexer-agent/bench/RESULTS.md`;

// The package is contexer-agent: the name "contexer" on PyPI belongs to another project.
export const INSTALL = "pip install contexer-agent";
export const INSTALL_TOOL = "uv tool install contexer-agent";

export const DESCRIPTION =
  "Contexer turns a goal into checks you approve, has your coding agent build it, and proves every check in a real browser before the change reaches review.";
