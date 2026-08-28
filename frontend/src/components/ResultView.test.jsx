import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { StageCard } from './ResultView'


describe('StageCard protocol evidence', () => {
  it('renders every protocol-specific evidence shape', () => {
    const stages = [
      {
        name: 'Council',
        reviews: { reviewer: { review: 'COUNCIL-REVIEW-MARKER' } },
        final: 'COUNCIL-FINAL-MARKER',
      },
      {
        name: 'Debate',
        proponent: { model: 'pro', argument: 'PRO-ARG-MARKER', rebuttal: 'PRO-REB-MARKER' },
        opponent: { model: 'con', argument: 'CON-ARG-MARKER', rebuttal: 'CON-REB-MARKER' },
        judge: 'JUDGE-MARKER',
        verdict: 'VERDICT-MARKER',
      },
      { name: 'Red team', attacker: 'ATTACKER-MARKER', critique: 'CRITIQUE-MARKER' },
      {
        name: 'Specialist',
        classification: 'CLASSIFY-MARKER',
        specialist: 'SPECIALIST-MARKER',
        answer: 'ANSWER-MARKER',
        verifications: { verifier: 'VERIFY-MARKER' },
      },
      {
        name: 'Tournament',
        matchups: [{ a: 'a', b: 'b', winner: 'a', verdict: 'MATCH-MARKER' }],
        winner: 'WINNER-MARKER',
      },
      {
        name: 'Auto',
        subtasks: [{ desc: 'SUBTASK-MARKER', model: 'worker', status: 'done', result: 'RESULT-MARKER' }],
      },
    ]

    const markup = stages
      .map((stage, index) => renderToStaticMarkup(<StageCard stage={stage} index={index} />))
      .join('\n')

    for (const marker of [
      'COUNCIL-REVIEW-MARKER',
      'COUNCIL-FINAL-MARKER',
      'PRO-ARG-MARKER',
      'PRO-REB-MARKER',
      'CON-ARG-MARKER',
      'CON-REB-MARKER',
      'JUDGE-MARKER',
      'VERDICT-MARKER',
      'ATTACKER-MARKER',
      'CRITIQUE-MARKER',
      'CLASSIFY-MARKER',
      'SPECIALIST-MARKER',
      'ANSWER-MARKER',
      'VERIFY-MARKER',
      'MATCH-MARKER',
      'WINNER-MARKER',
      'SUBTASK-MARKER',
      'RESULT-MARKER',
    ]) {
      expect(markup).toContain(marker)
    }
  })

  it('routes nested evidence through SafeMarkdown', () => {
    const markup = renderToStaticMarkup(
      <StageCard
        index={0}
        stage={{ name: 'Attack', critique: '![pixel](https://example.invalid/private)' }}
      />,
    )

    expect(markup).not.toContain('<img')
    expect(markup).not.toContain('example.invalid')
    expect(markup).toContain('[image blocked: pixel]')
  })
})
