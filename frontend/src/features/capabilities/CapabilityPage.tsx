export interface CapabilityPageProps {
  kind: "knowledge" | "approvals";
  title: string;
  description: string;
}

export function CapabilityPage({ kind, title, description }: CapabilityPageProps) {
  return (
    <section className="feature-page" data-capability={kind}>
      <div className="feature-heading"><h1>{title}</h1></div>
      <div className="feature-card capability-boundary" role="status" aria-label="能力边界">
        <strong>能力边界</strong>
        <p>{description}</p>
      </div>
    </section>
  );
}
