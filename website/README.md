# Contexer website

The landing page: one static page, built with Next.js and Tailwind CSS.

```bash
npm ci
npm run dev        # http://localhost:3000
npm run build      # static pages in .next/; every route is prerendered
npm run lint && npm run typecheck
```

## Deploying

Set `SITE_URL` to the address the site is served from (for example
`https://contexer.example`). Social cards, the canonical URL, `robots.txt` and
the sitemap use it for absolute URLs; without it they point at localhost.

Any host that runs `next build` works (Vercel, Netlify, Render, Cloudflare).

## Design

The page follows the `baseline-ui` skill in `.agents/skills/`: Tailwind's
zinc palette with green only where something is proven, no gradients or glow,
no animation, balanced headings and tabular numbers. Code and terminal output
are real Contexer output, shown as text.

`public/og.png` (the social card) and `public/report.png` (a real report from
`contexer demo`) come from `marketing/launch-video`
(`npx remotion still OgImage ../../website/public/og.png`).
