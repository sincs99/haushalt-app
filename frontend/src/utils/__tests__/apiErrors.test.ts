import { describe, it, expect } from 'vitest'
import i18n from '../../i18n'
import { translateApiError } from '../apiErrors'

const t = i18n.global.t

function axiosError(detail: unknown) {
  return { message: 'Request failed', response: { data: { detail } } }
}

describe('translateApiError', () => {
  it('translates a structured detail.code via errors.<CODE>', () => {
    expect(translateApiError(axiosError({ code: 'INVALID_CREDENTIALS', message: 'x' }))).toBe(
      t('errors.INVALID_CREDENTIALS'),
    )
  })

  it('falls back to detail.message for unknown codes', () => {
    expect(translateApiError(axiosError({ code: 'NOPE_NOT_A_CODE', message: 'Fallback text' }))).toBe(
      'Fallback text',
    )
  })

  it('returns string details as-is', () => {
    expect(translateApiError(axiosError('Plain legacy error'))).toBe('Plain legacy error')
  })

  it('joins pydantic validation arrays', () => {
    const err = axiosError([{ msg: 'field required' }, { msg: 'too short' }, { loc: ['x'] }])
    expect(translateApiError(err)).toBe('field required, too short, {"loc":["x"]}')
  })

  it('reports network errors when there is no response', () => {
    expect(translateApiError({ message: 'Network Error' })).toBe(t('errors.network'))
  })

  it('uses error.message when a response exists without usable detail', () => {
    expect(translateApiError({ message: 'Boom', response: { data: {} } })).toBe('Boom')
  })

  it('returns the unknown fallback for empty input', () => {
    expect(translateApiError(undefined)).toBe(t('errors.unknown'))
    expect(translateApiError({})).toBe(t('errors.unknown'))
  })
})
