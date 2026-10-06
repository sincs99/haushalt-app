/**
 * Web NFC (nur Chrome auf Android): URL-Record auf einen NFC-Chip schreiben.
 * Auf allen anderen Plattformen ist `supported` false — die UI verweist dann
 * auf eine NFC-App (z. B. „NFC Tools“).
 */
import { ref } from 'vue'

interface NdefWriter {
  write(message: { records: { recordType: 'url'; data: string }[] }, options?: { signal?: AbortSignal }): Promise<void>
}

type NdefReaderConstructor = new () => NdefWriter

function ndefReaderConstructor(): NdefReaderConstructor | null {
  if (typeof window === 'undefined') return null
  const ctor = (window as unknown as { NDEFReader?: NdefReaderConstructor }).NDEFReader
  return typeof ctor === 'function' ? ctor : null
}

export function isWebNfcSupported(): boolean {
  return ndefReaderConstructor() !== null
}

export type NfcWriteError = 'unsupported' | 'permission' | 'aborted' | 'failed'

export function useNfcWriter() {
  const supported = isWebNfcSupported()
  const writing = ref(false)
  let controller: AbortController | null = null

  /** Wartet, bis ein Chip ans Gerät gehalten wird, und schreibt die URL. */
  async function writeUrl(url: string): Promise<void> {
    const Ctor = ndefReaderConstructor()
    if (!Ctor) throw Object.assign(new Error('Web NFC unsupported'), { kind: 'unsupported' as NfcWriteError })
    controller = new AbortController()
    writing.value = true
    try {
      await new Ctor().write({ records: [{ recordType: 'url', data: url }] }, { signal: controller.signal })
    } catch (err: any) {
      const kind: NfcWriteError =
        err?.name === 'NotAllowedError' ? 'permission' : err?.name === 'AbortError' ? 'aborted' : 'failed'
      throw Object.assign(err instanceof Error ? err : new Error(String(err)), { kind })
    } finally {
      writing.value = false
      controller = null
    }
  }

  function cancel() {
    controller?.abort()
  }

  return { supported, writing, writeUrl, cancel }
}
