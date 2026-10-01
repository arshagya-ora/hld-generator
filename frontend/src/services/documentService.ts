import api from './api'

export interface Document {
  id: string
  filename: string
  original_filename: string
  file_size_bytes: number
  file_size_mb: number
  mime_type?: string
  document_type: string
  document_label?: string
  cognee_dataset_name?: string
  uploaded_at: string
  created_at: string
}

export interface DocumentListResponse {
  documents: Document[]
  count: number
  page: number
  page_size: number
  total_pages: number
}

export interface DocumentUploadResponse {
  id: string
  filename: string
  original_filename: string
  file_size_bytes: number
  mime_type?: string
  document_type: string
  document_label?: string
  uploaded_at: string
}

class DocumentService {
  async uploadDocuments(
    files: File[],
    documentTypes: string[],
    documentLabels: string[]
  ): Promise<DocumentUploadResponse[]> {
    const formData = new FormData()

    files.forEach((file) => {
      formData.append('files', file)
    })

    documentTypes.forEach((type) => {
      formData.append('document_types', type)
    })

    documentLabels.forEach((label) => {
      formData.append('document_labels', label)
    })

    const response = await api.post<DocumentUploadResponse[]>(
      '/documents/upload',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )

    return response.data
  }

  async listDocuments(
    page: number = 1,
    pageSize: number = 20,
    documentType?: string
  ): Promise<DocumentListResponse> {
    const params: any = { page, page_size: pageSize }
    if (documentType) {
      params.document_type = documentType
    }

    const response = await api.get<DocumentListResponse>('/documents', { params })
    return response.data
  }

  async getDocument(documentId: string): Promise<Document> {
    const response = await api.get<Document>(`/documents/${documentId}`)
    return response.data
  }

  async deleteDocument(documentId: string): Promise<void> {
    await api.delete(`/documents/${documentId}`)
  }

  async updateDocument(
    documentId: string,
    documentType: string,
    documentLabel?: string
  ): Promise<Document> {
    const response = await api.patch<Document>(`/documents/${documentId}`, {
      document_type: documentType,
      document_label: documentLabel,
    })
    return response.data
  }
}

export default new DocumentService()
