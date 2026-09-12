// M4 媒体查看器纯逻辑测试（与 richtext/graphLayout 同一套零依赖 runner）。
//
// 运行：npm run test:media

import assert from 'assert';
import {
  ZOOM_MAX,
  ZOOM_MIN,
  clampZoom,
  frameMaxHeight,
  isQuarterTurn,
  nextRotation,
  transformStyle,
} from '../lib/mediaView';

let passed = 0;
const failures: string[] = [];

function check(name: string, fn: () => void) {
  try {
    fn();
    passed += 1;
    console.log(`  ok  ${name}`);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    failures.push(`${name}: ${msg}`);
    console.log(`FAIL  ${name}\n      ${msg}`);
  }
}

console.log('mediaView 测试');

check('1. 向右转 4 次回到 0°，向左转不出现负角度', () => {
  let r = 0;
  for (let i = 0; i < 4; i += 1) r = nextRotation(r, 90);
  assert.strictEqual(r, 0);
  assert.strictEqual(nextRotation(0, -90), 270);
  assert.strictEqual(nextRotation(270, 90), 0);
});

check('2. 角度始终落在 {0,90,180,270}', () => {
  for (let r = -720; r <= 720; r += 37) {
    const v = nextRotation(r, 90);
    assert.ok([0, 90, 180, 270].includes(v), `非法角度 ${v}`);
  }
});

check('3. 缩放夹在 [0.25, 4]，非法输入回落到 1', () => {
  assert.strictEqual(clampZoom(0.01), ZOOM_MIN);
  assert.strictEqual(clampZoom(99), ZOOM_MAX);
  assert.strictEqual(clampZoom(2), 2);
  assert.strictEqual(clampZoom(Number.NaN), 1);
});

check('4. 90/270 度被识别为"宽高互换"', () => {
  assert.strictEqual(isQuarterTurn(90), true);
  assert.strictEqual(isQuarterTurn(270), true);
  assert.strictEqual(isQuarterTurn(180), false);
  assert.strictEqual(isQuarterTurn(0), false);
});

check('5. transform 串含 rotate 与 scale', () => {
  assert.strictEqual(transformStyle(90, 2).transform, 'rotate(90deg) scale(2)');
  assert.strictEqual(transformStyle(0, 1).transform, 'rotate(0deg) scale(1)');
  // 越界的缩放也要被夹住
  assert.strictEqual(transformStyle(0, 99).transform, `rotate(0deg) scale(${ZOOM_MAX})`);
});

check('6. 旋转后容器最大高度不缩水（避免裁掉内容）', () => {
  assert.strictEqual(frameMaxHeight(400, 0, 1), 400);
  assert.ok(frameMaxHeight(400, 90, 1) >= 400);
  assert.ok(frameMaxHeight(400, 0, 2) >= 800);
});

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const f of failures) console.log(`  - ${f}`);
  process.exit(1);
}
