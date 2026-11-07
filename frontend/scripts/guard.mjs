/**
 * 极光设计系统守卫：零依赖静态检查。
 * 只检查展示层约束，不碰 API 契约 / 业务逻辑 / 测试文件。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const ROOT = new URL('..', import.meta.url).pathname
const SRC = join(ROOT, 'src')

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(tsx?|css)$/.test(name)) out.push(full)
  }
  return out
}

const files = walk(SRC)
const read = (p) => ({ path: relative(ROOT, p), text: readFileSync(p, 'utf8') })
const contents = files.map(read)
const html = readFileSync(join(ROOT, 'index.html'), 'utf8')

const checks = []
const scan = (label, pattern, { scope = contents, exclude = [] } = {}) => {
  const hits = []
  for (const { path, text } of scope) {
    if (exclude.some((p) => p.test(path))) continue
    text.split('\n').forEach((line, i) => {
      if (pattern.test(line)) hits.push(`${path}:${i + 1}  ${line.trim().slice(0, 110)}`)
    })
  }
  checks.push({ label, hits })
}

scan('外链字体 / 远程图片 / Material Symbols', /fonts\.googleapis\.com|fonts\.gstatic\.com|lh3\.googleusercontent\.com|material-symbols-outlined/, {
  scope: [...contents, { path: 'index.html', text: html }],
})
scan('遗留 dark-* / wechat-* 色板', /\b(?:bg|text|border|ring|from|to|via)-dark-|wechat-/)
// accent-primary/secondary/success/warning/error 是旧色板；accent-iris / accent-warn 是合法的 CSS accent-color 工具类
scan('遗留 accent 旧色板', /accent-(?:primary|secondary|success|warning|error)\b/)
scan('死动画类', /animate-in\b|slide-in-from-|bg-dark-750|bg-dark-850/)
scan('组件内硬编码 hex', /#[0-9a-fA-F]{6}\b/, {
  scope: contents.filter(({ path }) => path.endsWith('.tsx')),
  exclude: [/styleguide\/Styleguide\.tsx$/], // 预览页色卡是刻意展示 hex
})

// 9 个布局 token 是嵌套滚动的契约，必须逐字保留
const appLayout = readFileSync(join(SRC, 'appLayout.ts'), 'utf8')
const searchLayout = readFileSync(join(SRC, 'components/searchViewLayout.ts'), 'utf8')
const layoutTokens = [
  [appLayout, 'flex-1'], [appLayout, 'min-w-0'], [appLayout, 'min-h-0'], [appLayout, 'overflow-hidden'],
  [searchLayout, 'h-full'], [searchLayout, 'min-h-0'], [searchLayout, 'overflow-hidden'],
  [searchLayout, 'min-h-0'], [searchLayout, 'overflow-y-auto'],
]
const missing = layoutTokens.filter(([text, token]) => !new RegExp(`\\b${token.replace(/-/g, '\\-')}\\b`).test(text))
checks.push({ label: '布局 9 token', hits: missing.map(([, t]) => `缺失 ${t}`) })

let failed = 0
for (const { label, hits } of checks) {
  if (hits.length) {
    failed++
    console.error(`✗ ${label} (${hits.length})`)
    hits.slice(0, 8).forEach((h) => console.error(`    ${h}`))
  } else {
    console.log(`✓ ${label}`)
  }
}
console.log(`\n扫描 ${contents.length} 个源文件 + index.html，${checks.length} 项检查`)
if (failed) {
  console.error(`${failed} 项未通过`)
  process.exit(1)
}
console.log('设计系统守卫全部通过')
