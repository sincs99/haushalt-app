import { describe, it, expect } from 'vitest'
import i18n from '../../i18n'
import { translateApiError } from '../apiErrors'

const t = i18n.global.t

function axiosError(detail: unknown, status = 400) {
  return { message: 'Request failed', response: { status, data: { detail } } }
}

describe('translateApiError', () => {
  it('translates a structured detail.code via errors.<CODE>', () => {
    expect(translateApiError(axiosError({ code: 'INVALID_CREDENTIALS', message: 'x' }))).toBe(
      t('errors.INVALID_CREDENTIALS'),
    )
  })

  it('translates the generic DB conflict code (409 CONFLICT_RETRY) in DE and EN', () => {
    const err = axiosError({ code: 'CONFLICT_RETRY', message: 'The data was changed concurrently.' }, 409)
    const previous = i18n.global.locale.value
    try {
      for (const locale of ['de', 'en'] as const) {
        i18n.global.locale.value = locale
        expect(translateApiError(err)).toBe(t('errors.CONFLICT_RETRY'))
        expect(translateApiError(err)).not.toBe('The data was changed concurrently.')
      }
    } finally {
      i18n.global.locale.value = previous
    }
  })

  it('falls back to detail.message for unknown codes', () => {
    expect(translateApiError(axiosError({ code: 'NOPE_NOT_A_CODE', message: 'Fallback text' }))).toBe(
      'Fallback text',
    )
  })

  it('never shows English string details, maps them by status', () => {
    expect(translateApiError(axiosError('Todo not found in this household', 404))).toBe(t('errors.notFound'))
    expect(translateApiError(axiosError('list_id does not belong to this household', 400))).toBe(t('errors.validation'))
  })

  it('maps pydantic validation arrays to a readable message', () => {
    const err = axiosError([{ msg: 'field required' }, { msg: 'too short' }], 422)
    expect(translateApiError(err)).toBe(t('errors.validation'))
  })

  it('maps server errors', () => {
    expect(translateApiError({ message: 'Request failed with status code 500', response: { status: 500, data: {} } })).toBe(t('errors.server'))
  })

  it('reports network errors when there is no response', () => {
    expect(translateApiError({ message: 'Network Error' })).toBe(t('errors.network'))
  })

  it('does not show raw error.message when a response exists without usable detail', () => {
    expect(translateApiError({ message: 'Boom', response: { data: {} } })).toBe(t('errors.unknown'))
  })

  it('returns the unknown fallback for empty input', () => {
    expect(translateApiError(undefined)).toBe(t('errors.unknown'))
    expect(translateApiError({})).toBe(t('errors.unknown'))
  })
})
