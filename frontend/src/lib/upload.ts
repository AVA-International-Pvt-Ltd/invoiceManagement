const ACCEPTED_EXT = new Set(['.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif'])

export function isAcceptedUpload(file: File): boolean {
  const name = file.name.toLowerCase()
  const dot = name.lastIndexOf('.')
  if (dot === -1) return false
  return ACCEPTED_EXT.has(name.slice(dot))
}

export function displayFileName(file: File): string {
  const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath
  return relative || file.name
}

/** Read every file inside dropped folder(s), recursively. */
async function readDirectoryEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  const all: FileSystemEntry[] = []
  let batch: FileSystemEntry[] = []
  do {
    batch = await new Promise<FileSystemEntry[]>((resolve, reject) => {
      reader.readEntries(resolve, reject)
    })
    all.push(...batch)
  } while (batch.length > 0)
  return all
}

async function entriesToFiles(entries: FileSystemEntry[]): Promise<File[]> {
  const files: File[] = []

  for (const entry of entries) {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => {
        ;(entry as FileSystemFileEntry).file(resolve, reject)
      })
      files.push(file)
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader()
      const nested = await readDirectoryEntries(reader)
      files.push(...(await entriesToFiles(nested)))
    }
  }

  return files
}

/** Collect files from drag-and-drop, including full folders. */
export async function collectDroppedFiles(dataTransfer: DataTransfer): Promise<File[]> {
  const items = dataTransfer.items

  if (items && items.length > 0 && typeof items[0].webkitGetAsEntry === 'function') {
    const entries: FileSystemEntry[] = []
    for (let i = 0; i < items.length; i += 1) {
      const entry = items[i].webkitGetAsEntry()
      if (entry) entries.push(entry)
    }
    if (entries.length > 0) {
      const all = await entriesToFiles(entries)
      return all.filter(isAcceptedUpload)
    }
  }

  return Array.from(dataTransfer.files).filter(isAcceptedUpload)
}

export function collectInputFiles(fileList: FileList | File[]): File[] {
  return Array.from(fileList).filter(isAcceptedUpload)
}

export const ACCEPTED_UPLOAD_LABEL = 'PDF, JPG, PNG, TIFF'

export const ACCEPTED_UPLOAD_ACCEPT = '.pdf,.jpg,.jpeg,.png,.tiff,.tif'
