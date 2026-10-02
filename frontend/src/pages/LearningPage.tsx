import { BrainCircuit } from 'lucide-react'

import { PlaceholderPage } from '@/components/layout/PlaceholderPage'

export function LearningPage() {
  return (
    <PlaceholderPage
      title="Learning"
      description="How the system learns from its own closed trades — and the guardrails around it."
      icon={BrainCircuit}
      emptyTitle="No models trained yet"
      emptyDescription="Model health appears here after enough closed trades exist to train and validate the meta-labeling model."
      planned={[
        'Champion vs challenger metrics',
        'Calibration and feature drift alerts',
        'Bandit allocator weights over time',
        'Promotion history and guardrails',
      ]}
    />
  )
}
