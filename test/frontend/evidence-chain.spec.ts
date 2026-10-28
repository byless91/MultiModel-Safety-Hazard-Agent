import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import EvidenceChain from '../../frontend/src/components/EvidenceChain.vue'
import { makeAssessment } from './fixtures/assessment'

const stubs = {
  'el-tag': { template: '<span><slot /></span>' },
  'el-empty': { props: ['description'], template: '<p>{{ description }}</p>' },
}

describe('root suite: real Vue component and evidence input', () => {
  it('shows an explicit empty state when there are no findings', () => {
    const wrapper = shallowMount(EvidenceChain, {
      props: { assessment: makeAssessment() },
      global: { stubs },
    })
    expect(wrapper.text()).toContain('暂无证据链可展示')
    expect(wrapper.text()).toContain('证据未判定')
    wrapper.unmount()
  })

  it('links only the evidence referenced by a concrete finding', () => {
    const assessment = makeAssessment()
    assessment.evidence = [
      { id: 'linked', source: 'R0_TEST_ONLY_EVIDENCE', text: '已引用原文', version: 'test', tags: [], score: 0.8 },
      { id: 'unlinked', source: '不得展示的无关依据', text: '无关原文', version: 'test', tags: [], score: 0.9 },
    ]
    assessment.findings = [{
      finding_id: 'finding-1', category: '占用疏散通道', description: '楼道堆物',
      final_confidence: 0.7, observed_facts: ['通道堆放纸箱'], uncertainties: [],
      model_support: ['mock'], locations: [], source: 'mock', evidence_status: 'insufficient',
      evidence_ids: ['linked'],
    }]
    const wrapper = shallowMount(EvidenceChain, { props: { assessment }, global: { stubs } })
    expect(wrapper.text()).toContain('已引用原文')
    expect(wrapper.text()).toContain('R0_TEST_ONLY_EVIDENCE')
    expect(wrapper.text()).not.toContain('不得展示的无关依据')
    wrapper.unmount()
  })
})
