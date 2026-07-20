import { describe, expect, it } from 'vitest'

import { splitCheckpointName } from './checkpointName'

describe('splitCheckpointName', () => {
  it('splits a trailing four-digit checkpoint index from the name', () => {
    expect(splitCheckpointName('Seq_RottenVale_WP_0026')).toEqual({
      name: 'Seq_RottenVale_WP',
      index: '0026',
    })
    expect(splitCheckpointName('Seq_village_0000')).toEqual({
      name: 'Seq_village',
      index: '0000',
    })
  })

  it('keeps names without an exact four-digit suffix intact', () => {
    expect(splitCheckpointName('Seq_RottenVale_WP')).toEqual({
      name: 'Seq_RottenVale_WP',
      index: '',
    })
    expect(splitCheckpointName('Seq_RottenVale_WP_026')).toEqual({
      name: 'Seq_RottenVale_WP_026',
      index: '',
    })
    expect(splitCheckpointName('Seq_RottenVale_WP_00260')).toEqual({
      name: 'Seq_RottenVale_WP_00260',
      index: '',
    })
  })

  it('handles empty or non-string values without throwing', () => {
    expect(splitCheckpointName('')).toEqual({ name: '', index: '' })
    expect(splitCheckpointName(null)).toEqual({ name: '', index: '' })
  })
})
