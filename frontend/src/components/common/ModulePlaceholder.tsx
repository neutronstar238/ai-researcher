/**
 * 尚未交付模块的占位页。
 * 这不是"功能开发中"Toast，而是明确说明该模块归属的交付阶段；对应 Phase 落地后删除。
 */
export function ModulePlaceholder({ module, phase }: { module: string; phase: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <div className="text-lg font-semibold text-text">{module}</div>
      <div className="text-sm text-text-muted">该模块将在 {phase} 交付，当前阶段尚未实现。</div>
    </div>
  );
}
