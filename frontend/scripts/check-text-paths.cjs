// M1 展示路径门禁：**穷举**列出所有会显示论文文本的位置，禁止"裸插值"。
//
// 为什么需要：D-71 把渲染内核统一了，但漏掉了四处"直接插值"的展示点
// （`QAView` 证据卡 ×2、`GraphView` 证据引文、`PresenterView` 引文 + `EvidenceDrawer`），
// 于是用户仍然看到 `For the base model, we use a rate of $P _ { d r o p } = 0 . 1$` 原文。
// 漏面是靠人眼发现的 —— 这个脚本把它变成**穷举门禁**：
//
//   1. 维护一份"展示路径清单"（下面 TARGETS：文件 + 字段说明）；
//   2. 在这些文件里，禁止把证据/引文/回答字段**直接当 JSX 子节点插值**
//      （例如 `>{e.source_text}<`、`>{e.quote || e.text}<`）——
//      必须经过 `<MathText>` / `<RichText>`；
//   3. `--self-test`：往检测器里塞一个已知坏样本，断言**它必须被报出来**
//      （一个永远不会失败的门禁等于没有门禁）。
//
// 用法：node scripts/check-text-paths.cjs [--self-test]
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');

/** 展示论文文本的位置清单：**新增展示点时必须登记**，否则门禁覆盖不到。 */
const TARGETS = [
  { file: 'components/views/QAView.tsx', what: '问答正文 + 证据引文卡' },
  { file: 'components/views/GraphView.tsx', what: '图谱节点证据引文' },
  { file: 'components/views/PresenterView.tsx', what: '讲解分镜引文/正文' },
  { file: 'components/evidence/EvidenceDrawer.tsx', what: '证据抽屉原文' },
  { file: 'components/source/SourceMedia.tsx', what: '媒体题注' },
  // R4 追加：这两处此前**不在白名单里**，于是 `{t.caption}` / `{f.caption}` 的裸插值
  // 一直没被门禁发现 —— 用户看到的就是 `<sup>†</sup>` 与 `$\mathbf { B E R T ... }$`
  // 原样显示（题注没走富文本内核）。把文件登记进来，门禁才会真的扫它们。
  { file: 'components/views/ClaimView.tsx', what: '证据链：表格/图表题注与关键结论' },
  { file: 'components/views/MapView.tsx', what: '论文地图：图表题注' },
  { file: 'components/FigureImage.tsx', what: '图表图片与题注' },
  { file: 'components/views/PaperView.tsx', what: '结构化导读 / 全文原文' },
  { file: 'components/LongText.tsx', what: '长文段落' },
  { file: 'components/TableRender.tsx', what: '表格单元格' },
];

/**
 * 裸插值检测：`>{ ... 字段 ... }<`，字段名命中证据/引文/正文类。
 * 说明：`<MathText text={...} />` 之类是**属性位置**，不匹配本模式（正是我们要的）。
 */
const RAW_INTERP = />\{[^}]*\b(source_text|quote|proposed_quote|answer|body|summary|caption|\.text)\b[^}]*\}</;

function scanSource(source) {
  const hits = [];
  const lines = source.split('\n');
  lines.forEach((line, idx) => {
    if (RAW_INTERP.test(line)) hits.push({ line: idx + 1, text: line.trim().slice(0, 120) });
  });
  return hits;
}

function checkTargets(targets) {
  const failures = [];
  for (const target of targets) {
    const full = path.join(ROOT, target.file);
    if (!fs.existsSync(full)) {
      // 清单漂移：登记的组件文件不存在（改名/删除后忘了同步清单）→ 必须红，
      // 否则清单会慢慢腐化成"看起来在管、其实没管"。
      failures.push({ file: target.file, drift: true, hits: [] });
      continue;
    }
    const hits = scanSource(fs.readFileSync(full, 'utf8'));
    if (hits.length > 0) failures.push({ file: target.file, what: target.what, hits });
  }
  return failures;
}

function main() {
  const selfTest = process.argv.includes('--self-test');
  if (selfTest) {
    const bad = '          <p className="x">{e.source_text}</p>';
    const good = '          <MathText text={e.source_text} className="x" />';
    const cases = [
      ['坏样本必被检出', scanSource(bad).length > 0],
      ['合规写法不误报', scanSource(good).length === 0],
      [
        '注入检测：已登记文件里插一条裸插值 → 必须红',
        scanSource(`${good}\n${bad}`).length > 0,
      ],
      [
        '清单漂移：登记了不存在的组件 → 必须红',
        checkTargets([{ file: 'components/views/__does_not_exist__.tsx', what: '漂移用例' }])
          .some((f) => f.drift),
      ],
    ];
    let failed = 0;
    for (const [name, ok] of cases) {
      if (ok) {
        console.log(`ok   自验证：${name}`);
      } else {
        console.error(`FAIL 自验证：${name}`);
        failed += 1;
      }
    }
    if (failed) process.exit(1);
    return;
  }

  const failures = checkTargets(TARGETS);
  if (failures.length > 0) {
    for (const f of failures) {
      if (f.drift) {
        console.error(`FAIL 清单漂移：${f.file} 不存在（清单过期了？）`);
        continue;
      }
      console.error(`FAIL ${f.file}（${f.what}）存在裸插值：`);
      for (const h of f.hits) console.error(`     ${h.line}: ${h.text}`);
    }
    console.error(
      `\n结论：${failures.length} 处问题 ❌（裸插值改用 <MathText>/<RichText>；漂移项请同步清单）`,
    );
    process.exit(1);
  }
  console.log(`结论：清单内 ${TARGETS.length} 个展示点的论文文本都经过渲染内核 ✅`);
}

main();
