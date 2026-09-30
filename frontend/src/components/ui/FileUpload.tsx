import { useState, useRef, DragEvent } from 'react'
import { Upload, X, File as FileIcon } from 'lucide-react'
import Button from './Button'
import Select from './Select'
import Input from './Input'
import styles from './FileUpload.module.css'

export interface FileWithMeta {
  file: File
  pageCount: number
  documentType: string
  documentLabel: string
  id: string
}

interface FileUploadProps {
  onFilesChange: (files: FileWithMeta[]) => void
  accept?: string
  maxPages?: number
  multiple?: boolean
  className?: string
}

const DOCUMENT_TYPES = [
  { value: 'PID', label: 'PID (Product Introduction Document)' },
  { value: 'RD', label: 'RD (Reference Document)' },
  { value: 'DIAGRAM', label: 'DIAGRAM' },
  { value: 'OTHER', label: 'OTHER' },
]

interface ZipEntry {
  name: string
  compressionMethod: number
  compressedSize: number
  localHeaderOffset: number
}

const getFileExtension = (fileName: string) =>
  '.' + fileName.split('.').pop()?.toLowerCase()

const pluralizePage = (pageCount: number) => `${pageCount} page${pageCount === 1 ? '' : 's'}`

const getPdfPageCount = async (file: File) => {
  const buffer = await file.arrayBuffer()
  const text = new TextDecoder('latin1').decode(buffer)
  return text.match(/\/Type\s*\/Page(?!s)\b/g)?.length ?? 0
}

const listZipEntries = async (file: File): Promise<{ buffer: ArrayBuffer; entries: ZipEntry[] }> => {
  const buffer = await file.arrayBuffer()
  const view = new DataView(buffer)
  const minEndRecordSize = 22
  const maxCommentSize = 0xffff
  const searchStart = Math.max(0, buffer.byteLength - minEndRecordSize - maxCommentSize)
  let endRecordOffset = -1

  for (let offset = buffer.byteLength - minEndRecordSize; offset >= searchStart; offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50) {
      endRecordOffset = offset
      break
    }
  }

  if (endRecordOffset === -1) {
    throw new Error('Invalid Office document')
  }

  const centralDirectorySize = view.getUint32(endRecordOffset + 12, true)
  const centralDirectoryOffset = view.getUint32(endRecordOffset + 16, true)
  const entries: ZipEntry[] = []
  let offset = centralDirectoryOffset
  const directoryEnd = centralDirectoryOffset + centralDirectorySize

  while (offset < directoryEnd) {
    if (view.getUint32(offset, true) !== 0x02014b50) {
      break
    }

    const compressionMethod = view.getUint16(offset + 10, true)
    const compressedSize = view.getUint32(offset + 20, true)
    const fileNameLength = view.getUint16(offset + 28, true)
    const extraFieldLength = view.getUint16(offset + 30, true)
    const fileCommentLength = view.getUint16(offset + 32, true)
    const localHeaderOffset = view.getUint32(offset + 42, true)
    const fileNameBytes = new Uint8Array(buffer, offset + 46, fileNameLength)
    const name = new TextDecoder().decode(fileNameBytes)

    entries.push({
      name,
      compressionMethod,
      compressedSize,
      localHeaderOffset,
    })

    offset += 46 + fileNameLength + extraFieldLength + fileCommentLength
  }

  return { buffer, entries }
}

const readZipEntry = async (buffer: ArrayBuffer, entry: ZipEntry) => {
  const view = new DataView(buffer)
  const headerOffset = entry.localHeaderOffset

  if (view.getUint32(headerOffset, true) !== 0x04034b50) {
    throw new Error('Invalid Office document entry')
  }

  const fileNameLength = view.getUint16(headerOffset + 26, true)
  const extraFieldLength = view.getUint16(headerOffset + 28, true)
  const dataOffset = headerOffset + 30 + fileNameLength + extraFieldLength
  const compressedData = buffer.slice(dataOffset, dataOffset + entry.compressedSize)

  if (entry.compressionMethod === 0) {
    return compressedData
  }

  if (entry.compressionMethod === 8 && 'DecompressionStream' in window) {
    const stream = new Blob([compressedData]).stream()
    const decompressedStream = stream.pipeThrough(new DecompressionStream('deflate-raw'))
    return new Response(decompressedStream).arrayBuffer()
  }

  throw new Error('Unsupported Office document compression')
}

const getOfficePageCount = async (file: File, ext: string) => {
  const { buffer, entries } = await listZipEntries(file)

  if (ext === '.pptx') {
    return entries.filter((entry) => /^ppt\/slides\/slide\d+\.xml$/.test(entry.name)).length
  }

  if (ext === '.docx') {
    const appMetadataEntry = entries.find((entry) => entry.name === 'docProps/app.xml')

    if (!appMetadataEntry) {
      throw new Error('Could not read document page count')
    }

    const appMetadata = await readZipEntry(buffer, appMetadataEntry)
    const appMetadataText = new TextDecoder().decode(appMetadata)
    const pages = Number(appMetadataText.match(/<Pages>(\d+)<\/Pages>/)?.[1])

    if (!Number.isFinite(pages) || pages < 1) {
      throw new Error('Could not read document page count')
    }

    return pages
  }

  throw new Error('Page count validation is not supported for this file type')
}

const getFilePageCount = async (file: File) => {
  const ext = getFileExtension(file.name)

  if (ext === '.pdf') {
    const pages = await getPdfPageCount(file)

    if (pages < 1) {
      throw new Error('Could not read PDF page count')
    }

    return pages
  }

  if (ext === '.docx' || ext === '.pptx') {
    const pages = await getOfficePageCount(file, ext)

    if (pages < 1) {
      throw new Error('Could not read document page count')
    }

    return pages
  }

  if (['.png', '.jpg', '.jpeg'].includes(ext)) {
    return 1
  }

  throw new Error('Page count validation is not supported for this file type')
}

export default function FileUpload({
  onFilesChange,
  accept = '.docx,.pptx,.pdf,.png,.jpg,.jpeg',
  maxPages = 50,
  multiple = true,
  className = '',
}: FileUploadProps) {
  const [files, setFiles] = useState<FileWithMeta[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const generateId = () => Math.random().toString(36).substring(7)

  const handleFiles = async (newFiles: FileList | null) => {
    if (!newFiles) return

    const validFiles: FileWithMeta[] = []

    for (const file of Array.from(newFiles)) {
      // Validate type
      const ext = getFileExtension(file.name)
      if (!accept.includes(ext)) {
        alert(`File type "${ext}" not allowed`)
        continue
      }

      let pageCount: number

      try {
        pageCount = await getFilePageCount(file)
      } catch (error: any) {
        alert(`Could not validate page count for "${file.name}". ${error.message}`)
        continue
      }

      if (pageCount > maxPages) {
        alert(`File "${file.name}" has ${pluralizePage(pageCount)} and exceeds the ${maxPages} page limit`)
        continue
      }

      validFiles.push({
        file,
        pageCount,
        documentType: 'OTHER',
        documentLabel: file.name,
        id: generateId(),
      })
    }

    const updatedFiles = multiple ? [...files, ...validFiles] : validFiles
    setFiles(updatedFiles)
    onFilesChange(updatedFiles)
  }

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    handleFiles(e.target.files)
  }

  const handleRemoveFile = (id: string) => {
    const updatedFiles = files.filter((f) => f.id !== id)
    setFiles(updatedFiles)
    onFilesChange(updatedFiles)
  }

  const handleTypeChange = (id: string, type: string) => {
    const updatedFiles = files.map((f) =>
      f.id === id ? { ...f, documentType: type } : f
    )
    setFiles(updatedFiles)
    onFilesChange(updatedFiles)
  }

  const handleLabelChange = (id: string, label: string) => {
    const updatedFiles = files.map((f) =>
      f.id === id ? { ...f, documentLabel: label } : f
    )
    setFiles(updatedFiles)
    onFilesChange(updatedFiles)
  }

  return (
    <div className={`${styles.fileUpload} ${className}`}>
      <div
        className={`${styles.dropZone} ${isDragging ? styles.dragging : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <Upload size={48} className={styles.uploadIcon} />
        <p className={styles.dropText}>
          Drag & drop files here, or <span className={styles.browseText}>browse</span>
        </p>
        <p className={styles.acceptText}>
          Accepted: {accept} (Max {maxPages} pages per file)
        </p>

        <input
          ref={fileInputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          onChange={handleFileInputChange}
          className={styles.fileInput}
        />
      </div>

      {files.length > 0 && (
        <div className={styles.filesList}>
          <h4 className={styles.filesHeader}>
            Selected Files ({files.length})
          </h4>

          {files.map((fileWithMeta) => (
            <div key={fileWithMeta.id} className={styles.fileItem}>
              <div className={styles.fileInfo}>
                <FileIcon size={20} className={styles.fileIcon} />
                <div className={styles.fileDetails}>
                  <p className={styles.fileName}>{fileWithMeta.file.name}</p>
                  <p className={styles.fileSize}>
                    {pluralizePage(fileWithMeta.pageCount)}
                  </p>
                </div>
              </div>

              <div className={styles.fileControls}>
                <Select
                  options={DOCUMENT_TYPES}
                  value={fileWithMeta.documentType}
                  onChange={(e) => handleTypeChange(fileWithMeta.id, e.target.value)}
                  className={styles.typeSelect}
                />

                <Input
                  type="text"
                  placeholder="Document label"
                  value={fileWithMeta.documentLabel}
                  onChange={(e) => handleLabelChange(fileWithMeta.id, e.target.value)}
                  className={styles.labelInput}
                />

                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleRemoveFile(fileWithMeta.id)}
                  icon={<X size={16} />}
                  aria-label="Remove file"
                >
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
