import { describe, it, expect } from 'vitest'
import { errorI18n } from './apiError'

describe('errorI18n', () => {
  it('maps a known code to its i18n key with params', () => {
    const r = errorI18n({ code: 'FILE_TOO_LARGE', message: '檔案超過 3072MB 上限', params: { max: 3072 } })
    expect(r.key).toBe('errors.fileTooLarge')
    expect(r.params).toEqual({ max: 3072 })
    expect(r.fallback).toBe('檔案超過 3072MB 上限')
  })

  it('returns null key but keeps message fallback for unknown code', () => {
    const r = errorI18n({ code: 'SOME_NEW_CODE', message: '尚未對應的訊息' })
    expect(r.key).toBeNull()
    expect(r.fallback).toBe('尚未對應的訊息')
  })

  it('handles a raw string detail (legacy endpoints)', () => {
    const r = errorI18n('純字串錯誤')
    expect(r.key).toBeNull()
    expect(r.fallback).toBe('純字串錯誤')
  })

  it('unwraps an axios error (response.data.detail)', () => {
    const r = errorI18n({ response: { data: { detail: { code: 'UPLOAD_DISK_FULL', message: '空間不足' } } } })
    expect(r.key).toBe('errors.uploadDiskFull')
    expect(r.fallback).toBe('空間不足')
  })

  it('defaults params to empty object when absent', () => {
    const r = errorI18n({ code: 'INVALID_FILE_SIZE', message: 'x' })
    expect(r.params).toEqual({})
  })
})
