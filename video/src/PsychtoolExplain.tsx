// psychtool 说明片 v2 — 真实工作流叙事（自主自由创作模式）
// 叙事：定位 → 候选陈述(归属+来源定位) → 矛盾保留 → 脱敏 → 带来源草稿+索引 → 收尾
// 视觉沿用产品 tokens：纸面 #FAF8F2 / 墨色 #1F2430 / 靛蓝 #4C6EF5 / 脱敏琥珀 #C46F34，等宽字体，索引卡。
// 内容全部来自 psychtool 真实输出（fixtures TRAIN-A 与 core/redact.py 的 token 形态）。
import React from 'react';
import {
  AbsoluteFill,
  useCurrentFrame,
  interpolate,
  Easing,
} from 'remotion';

export const PSYCHTOOL_EXPLAIN_DURATION = 720; // 24s @ 30fps

const C = {
  paper: '#FAF8F2',
  ink: '#1F2430',
  muted: '#6E7681',
  accent: '#4C6EF5',
  self: '#4C6EF5',
  caregiver: '#0e9f6e',
  teacher: '#f26a1b',
  redact: '#C46F34',
  line: '#E4E0D8',
  card: '#FFFFFF',
};

const MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Microsoft YaHei", monospace';
const SANS = '"PingFang SC", "Microsoft YaHei", -apple-system, "Segoe UI", sans-serif';

const CLAIMS = [
  { id: 'A-F1', role: '本人', roleColor: C.self, src: 'A-YOUTH · A-Y1', text: '本人报告九月开学后作业用时变长，同时仍按时参加科学社。' },
  { id: 'A-F3', role: '照护者', roleColor: C.caregiver, src: 'A-CAREGIVER · A-C1', text: '照护者把变化开始时间描述为七月，与本人的九月说明不同。' },
  { id: 'A-F4', role: '教师', roleColor: C.teacher, src: 'A-SCHOOL · A-S1', text: '教师称九月四份课堂练习按时交回，但没有家庭作业观察。' },
];

const SOURCE_INDEX = [
  { id: 'A-F1', loc: 'A-YOUTH v1 段落 A-Y1', text: '本人报告九月开学后作业用时变长，同时仍按时参加科学社。' },
  { id: 'A-F3', loc: 'A-CAREGIVER v1 段落 A-C1', text: '照护者把变化开始时间描述为七月，与本人的九月说明不同。' },
];

const appear = (f: number, t0: number, dur: number) =>
  interpolate(f, [t0, t0 + dur], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
const slideY = (f: number, t0: number, dur: number, from = 28) => from * (1 - appear(f, t0, dur));

const T = { s1: 0, s2: 90, s3: 270, s4: 390, s5: 510, s6: 640 };

export const PsychtoolExplain: React.FC = () => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: C.paper, fontFamily: SANS, color: C.ink }}>
      <div style={{ position: 'absolute', left: 80, top: 56, display: 'flex', alignItems: 'center', gap: 16 }}>
        <span style={{ width: 44, height: 44, borderRadius: 12, background: C.accent, display: 'grid', placeItems: 'center', fontFamily: MONO, fontWeight: 800, color: '#fff', fontSize: 22 }}>p</span>
        <span style={{ fontFamily: MONO, fontSize: 26, fontWeight: 700 }}>psychtool</span>
        <span style={{ color: C.muted, fontSize: 22 }}>来源可溯的临床写作</span>
      </div>
      <Scene1 f={f} />
      <Scene2 f={f} />
      <Scene3 f={f} />
      <Scene4Redact f={f} />
      <Scene5 f={f} />
      <Scene6 f={f} />
    </AbsoluteFill>
  );
};

const Scene1: React.FC<{ f: number }> = ({ f }) => {
  const p = appear(f, T.s1, 24);
  const steps = ['材料', '事实清单', '脱敏', '草稿', '审阅'];
  return (
    <div style={{ position: 'absolute', inset: 0, opacity: f > T.s2 - 20 ? 0 : 1 }}>
      <div style={{ position: 'absolute', left: 80, top: 300, maxWidth: 1080 }}>
        <div style={{ fontFamily: MONO, fontSize: 20, color: C.accent, letterSpacing: '0.18em', opacity: p, transform: `translateY(${slideY(f, T.s1, 24)}px)` }}>
          个案 TRAIN-A · 三个信息提供者
        </div>
        <div style={{ fontSize: 76, fontWeight: 800, lineHeight: 1.08, marginTop: 18, opacity: p, transform: `translateY(${slideY(f, T.s1 + 6, 24)}px)` }}>
          每条陈述，<br />都回到它的来源
        </div>
        <div style={{ fontSize: 30, color: C.muted, marginTop: 26, opacity: p, transform: `translateY(${slideY(f, T.s1 + 12, 24)}px)` }}>
          把分散材料整理成报告时，保留谁、在什么场合、以什么确定性说了什么。
        </div>
      </div>
      <div style={{ position: 'absolute', left: 80, bottom: 140, display: 'flex', alignItems: 'center', gap: 12, fontFamily: MONO, fontSize: 26 }}>
        {steps.map((s, i) => (
          <React.Fragment key={s}>
            <span style={{ opacity: appear(f, T.s1 + 18 + i * 8, 16), background: i === 2 ? C.redact : C.card, border: `1px solid ${C.line}`, color: i === 2 ? '#fff' : C.ink, padding: '10px 18px', borderRadius: 10 }}>{s}</span>
            {i < steps.length - 1 && <span style={{ color: C.muted }}>→</span>}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

const Scene2: React.FC<{ f: number }> = ({ f }) => {
  const base = T.s2;
  if (f < base || f >= T.s3) return null;
  return (
    <div style={{ position: 'absolute', left: 80, top: 220, right: 80 }}>
      <div style={{ fontFamily: MONO, fontSize: 20, color: C.accent, letterSpacing: '0.14em', opacity: appear(f, base, 14) }}>
        候选陈述 · 归属与来源定位
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 22, marginTop: 30 }}>
        {CLAIMS.map((c, i) => {
          const p = appear(f, base + 14 + i * 22, 20);
          return (
            <div key={c.id} style={{
              display: 'flex', alignItems: 'flex-start', gap: 22, background: C.card,
              border: `1px solid ${C.line}`, borderRadius: 14, padding: '24px 28px',
              boxShadow: '0 10px 30px -18px rgba(31,36,48,0.18)',
              opacity: p, transform: `translateY(${slideY(f, base + 14 + i * 22, 20)}px)`,
            }}>
              <span style={{ fontFamily: MONO, fontSize: 20, color: C.muted, paddingTop: 2, minWidth: 74 }}>{c.id}</span>
              <span style={{ fontSize: 20, color: c.roleColor, fontWeight: 700, background: `${c.roleColor}18`, padding: '4px 14px', borderRadius: 8, whiteSpace: 'nowrap' }}>{c.role}</span>
              <span style={{ fontFamily: MONO, fontSize: 20, color: C.muted, whiteSpace: 'nowrap', paddingTop: 2 }}>来源 {c.src}</span>
              <span style={{ fontSize: 28, lineHeight: 1.35 }}>{c.text}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const Scene3: React.FC<{ f: number }> = ({ f }) => {
  const base = T.s3;
  if (f < base || f >= T.s4) return null;
  const p = appear(f, base, 18);
  return (
    <div style={{ position: 'absolute', left: 80, top: 240, right: 80 }}>
      <div style={{ fontFamily: MONO, fontSize: 20, color: C.accent, letterSpacing: '0.14em', opacity: p }}>
        矛盾 · 显式保留，不替双方裁决
      </div>
      <div style={{ display: 'flex', gap: 26, marginTop: 34, opacity: p, transform: `translateY(${slideY(f, base, 18)}px)` }}>
        {[
          { role: '照护者', color: C.caregiver, big: '七月', text: '「我觉得作业变慢从七月就开始了，不是九月。」' },
          { role: '本人', color: C.self, big: '九月', text: '「我在九月开学后开始觉得作业用时变长。」' },
        ].map((x, i) => (
          <div key={i} style={{ flex: 1, background: C.card, border: `1px solid ${C.line}`, borderRadius: 16, padding: '30px 32px' }}>
            <span style={{ fontSize: 20, color: x.color, fontWeight: 700 }}>{x.role}</span>
            <div style={{ fontFamily: MONO, fontSize: 72, fontWeight: 800, color: x.color, marginTop: 8 }}>{x.big}</div>
            <div style={{ fontSize: 26, color: C.muted, marginTop: 12, lineHeight: 1.4 }}>{x.text}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 30, display: 'flex', alignItems: 'center', gap: 14, opacity: appear(f, base + 30, 16) }}>
        <span style={{ width: 14, height: 14, borderRadius: 7, background: C.teacher }} />
        <span style={{ fontSize: 26, fontWeight: 700 }}>保留两种说法，标记「待核对」——不替他们选一个日期。</span>
      </div>
    </div>
  );
};

// —— 新增：脱敏场景 ——
const Hi: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ color: C.redact, fontWeight: 700, background: `${C.redact}1A`, padding: '1px 6px', borderRadius: 6 }}>{children}</span>
);

const Tok: React.FC<{ t: number; delay: number; children: React.ReactNode }> = ({ t, delay, children }) => {
  const o = interpolate(t, [delay, delay + 8], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <b style={{ color: C.redact, opacity: o, display: 'inline-block', transform: `translateY(${(1 - o) * 6}px)` }}>{children}</b>
  );
};

const Scene4Redact: React.FC<{ f: number }> = ({ f }) => {
  const base = T.s4;
  if (f < base || f >= T.s5) return null;
  const t = f - base - 24; // token reveal offset
  const p = appear(f, base, 16);
  return (
    <div style={{ position: 'absolute', left: 80, top: 210, right: 80 }}>
      <div style={{ fontFamily: MONO, fontSize: 20, color: C.redact, letterSpacing: '0.14em', opacity: p }}>
        脱敏 · 生成前抹掉标识符
      </div>
      <div style={{ fontSize: 34, fontWeight: 700, marginTop: 14, opacity: p }}>模型只看到 token，看不到真名与电话。</div>

      <div style={{ display: 'flex', alignItems: 'stretch', gap: 26, marginTop: 36, opacity: p }}>
        <div style={{ flex: 1, background: C.card, border: `1px solid ${C.line}`, borderRadius: 16, padding: '30px 34px' }}>
          <div style={{ fontFamily: MONO, fontSize: 18, color: C.muted, marginBottom: 16 }}>原始材料</div>
          <div style={{ fontFamily: MONO, fontSize: 30, lineHeight: 1.75 }}>
            个案 <Hi>陈小雨</Hi> 于 <Hi>2026-10-12</Hi> 由母亲陪同，联系电话 <Hi>(312) 555-0142</Hi>。
          </div>
        </div>
        <div style={{ display: 'grid', placeItems: 'center', fontFamily: MONO, fontSize: 44, color: C.redact, opacity: appear(f, base + 18, 14) }}>→</div>
        <div style={{ flex: 1, background: '#FBF1E6', border: `1px solid ${C.redact}55`, borderRadius: 16, padding: '30px 34px' }}>
          <div style={{ fontFamily: MONO, fontSize: 18, color: C.redact, marginBottom: 16 }}>发给模型的 token</div>
          <div style={{ fontFamily: MONO, fontSize: 30, lineHeight: 1.75, color: C.ink }}>
            个案 <Tok t={t} delay={0}>[[NAME_1]]</Tok> 于 <Tok t={t} delay={10}>[[DATE_1]]</Tok> 由母亲陪同，联系电话 <Tok t={t} delay={20}>[[TELEPHONE_1]]</Tok>。
          </div>
        </div>
      </div>

      <div style={{ marginTop: 28, display: 'flex', alignItems: 'center', gap: 14, opacity: appear(f, base + 96, 16) }}>
        <span style={{ width: 14, height: 14, borderRadius: 7, background: C.redact }} />
        <span style={{ fontSize: 26, fontWeight: 700 }}>Safe Harbor 18 类标识符先换成 token；生成后只在本地还原，标识符永不出网。</span>
      </div>
    </div>
  );
};

const Scene5: React.FC<{ f: number }> = ({ f }) => {
  const base = T.s5;
  if (f < base || f >= T.s6) return null;
  const p = appear(f, base, 20);
  return (
    <div style={{ position: 'absolute', left: 80, top: 200, right: 80 }}>
      <div style={{ fontFamily: MONO, fontSize: 20, color: C.accent, letterSpacing: '0.14em', opacity: p }}>
        带来源草稿 · 每条事实性陈述可回溯
      </div>
      <div style={{ background: C.card, border: `1px solid ${C.line}`, borderRadius: 16, padding: '34px 38px', marginTop: 28, opacity: p, transform: `translateY(${slideY(f, base, 20)}px)` }}>
        <div style={{ fontSize: 30, lineHeight: 1.55 }}>
          背景：该学生本人报告九月开学后作业用时变长，同时仍按时参加科学社活动 <b style={{ color: C.self }}>[A-F1]</b>。照护者则把变化开始时间描述为七月，两者不一致，保留待核对 <b style={{ color: C.caregiver }}>[A-F3]</b>。
        </div>
        <div style={{ borderTop: `1px solid ${C.line}`, marginTop: 26, paddingTop: 24 }}>
          <div style={{ fontFamily: MONO, fontSize: 20, color: C.muted }}>## 来源索引</div>
          {SOURCE_INDEX.map((s, i) => (
            <div key={i} style={{ display: 'flex', gap: 16, marginTop: 14, opacity: appear(f, base + 30 + i * 18, 16), fontFamily: MONO, fontSize: 22 }}>
              <span style={{ color: C.accent, fontWeight: 700 }}>[{s.id}]</span>
              <span style={{ color: C.muted }}>{s.loc}</span>
              <span style={{ color: C.ink }}>{s.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const Scene6: React.FC<{ f: number }> = ({ f }) => {
  const base = T.s6;
  if (f < base) return null;
  const p = appear(f, base, 26);
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', textAlign: 'center' }}>
      <div style={{ opacity: p, transform: `translateY(${slideY(f, base, 26)}px)` }}>
        <div style={{ fontSize: 72, fontWeight: 800 }}>每条陈述，都回到它的来源</div>
        <div style={{ fontFamily: MONO, fontSize: 26, color: C.muted, marginTop: 22 }}>psychtool · source-traceable clinical writing</div>
      </div>
    </div>
  );
};

