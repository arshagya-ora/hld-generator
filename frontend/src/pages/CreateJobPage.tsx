import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import Card, { CardHeader, CardBody, CardFooter } from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import Select from '@/components/ui/Select'
import FileUpload, { FileWithMeta } from '@/components/ui/FileUpload'
import Alert from '@/components/ui/Alert'
import Spinner from '@/components/ui/Spinner'
import productService, { Product } from '@/services/productService'
import documentService from '@/services/documentService'
import { useJobsStore } from '@/stores/jobsStore'
import styles from './CreateJobPage.module.css'

export default function CreateJobPage() {
  const navigate = useNavigate()
  const createJob = useJobsStore((state) => state.createJob)

  const [products, setProducts] = useState<Product[]>([])
  const [selectedProduct, setSelectedProduct] = useState('')
  const [files, setFiles] = useState<FileWithMeta[]>([])
  const [userPrompt, setUserPrompt] = useState('')
  const [isLoadingProducts, setIsLoadingProducts] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [isCreatingJob, setIsCreatingJob] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadProducts()
  }, [])

  const loadProducts = async () => {
    try {
      const response = await productService.listProducts()
      setProducts(response.products)
    } catch (err: any) {
      setError('Failed to load products')
    } finally {
      setIsLoadingProducts(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Validation
    if (!selectedProduct) {
      setError('Please select a product')
      return
    }

    if (files.length === 0) {
      setError('Please upload at least one document')
      return
    }

    try {
      // Step 1: Upload documents
      setIsUploading(true)
      const uploadedDocs = await documentService.uploadDocuments(
        files.map((f) => f.file),
        files.map((f) => f.documentType),
        files.map((f) => f.documentLabel)
      )

      // Step 2: Create job
      setIsUploading(false)
      setIsCreatingJob(true)

      const job = await createJob(
        selectedProduct,
        uploadedDocs.map((d) => d.id),
        {
          output_format: 'docx',
          include_diagrams: true,
          verbosity: 'medium',
        },
        userPrompt || undefined
      )

      // Navigate to job detail page
      navigate(`/jobs/${job.id}`)
    } catch (err: any) {
      console.error('Job creation error:', err)
      setError(
        err.response?.data?.detail || 'Failed to create job. Please try again.'
      )
      setIsUploading(false)
      setIsCreatingJob(false)
    }
  }

  if (isLoadingProducts) {
    return (
      <div className={styles.loading}>
        <Spinner size="lg" />
        <p>Loading products...</p>
      </div>
    )
  }

  return (
    <div className={styles.createJobPage}>
      <div className={styles.header}>
        <h1 className={styles.title}>Create New HLD Generation Job</h1>
        <p className={styles.subtitle}>
          Select a product and upload your documents to generate a High-Level Design
        </p>
      </div>

      <form onSubmit={handleSubmit}>
        <Card className={styles.card}>
          <CardHeader>
            <h2 className={styles.sectionTitle}>1. Select Product</h2>
          </CardHeader>
          <CardBody>
            {error && (
              <Alert variant="danger" onClose={() => setError('')} className={styles.alert}>
                {error}
              </Alert>
            )}

            {products.length === 0 && !error && (
              <Alert variant="warning" className={styles.alert}>
                No products are configured. Ask your administrator to add a product profile.
              </Alert>
            )}

            <Select
              label="Product"
              placeholder="Choose a product..."
              options={products.map((p) => ({
                value: p.id,
                label: p.name,
              }))}
              value={selectedProduct}
              onChange={(e) => setSelectedProduct(e.target.value)}
              required
              helperText="Select the product for which you want to generate an HLD"
            />

            {selectedProduct && (
              <div className={styles.productInfo}>
                <p className={styles.productDescription}>
                  {products.find((p) => p.id === selectedProduct)?.description}
                </p>
              </div>
            )}
          </CardBody>
        </Card>

        <Card className={styles.card}>
          <CardHeader>
            <h2 className={styles.sectionTitle}>2. Upload Documents</h2>
          </CardHeader>
          <CardBody>
            <FileUpload
              onFilesChange={setFiles}
              accept=".docx,.pptx,.pdf,.png,.jpg,.jpeg"
              maxPages={50}
              multiple={true}
            />

            <div className={styles.documentTypes}>
              <h4>Document Types:</h4>
              <ul>
                <li><strong>PID:</strong> Product Introduction Document</li>
                <li><strong>RD:</strong> Reference Document</li>
                <li><strong>DIAGRAM:</strong> Architecture/System Diagrams</li>
                <li><strong>OTHER:</strong> Any other supporting documents</li>
              </ul>
            </div>
          </CardBody>
        </Card>

        <Card className={styles.card}>
          <CardHeader>
            <h2 className={styles.sectionTitle}>3. Instructions (Optional)</h2>
          </CardHeader>
          <CardBody>
            <div className={styles.promptSection}>
              <label htmlFor="userPrompt" className={styles.promptLabel}>
                Custom instructions for HLD generation
              </label>
              <textarea
                id="userPrompt"
                className={styles.promptTextarea}
                value={userPrompt}
                onChange={(e) => setUserPrompt(e.target.value)}
                placeholder={`Examples:

Customer: Example Customer
Product: ExampleGateway
Include sections: 1-3
Focus on capacity sizing and HA architecture

OR:

Include only BSF and SCP components
Detailed capacity sizing (>2000 tokens)
Use IP addresses from network_plan.xlsx`}
                rows={6}
              />
              <p className={styles.promptHelper}>
                Describe what to include, exclude, or emphasize. Leave blank for default full HLD generation.
              </p>
            </div>
          </CardBody>
        </Card>

        <Card className={styles.card}>
          <CardHeader>
            <h2 className={styles.sectionTitle}>4. Configuration</h2>
          </CardHeader>
          <CardBody>
            <div className={styles.configInfo}>
              <p><strong>Output Format:</strong> DOCX (Microsoft Word)</p>
              <p><strong>Include Diagrams:</strong> Yes</p>
              <p><strong>Verbosity:</strong> Medium</p>
            </div>
          </CardBody>
        </Card>

        <Card className={styles.submitCard}>
          <CardFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => navigate('/dashboard')}
              disabled={isUploading || isCreatingJob}
            >
              Cancel
            </Button>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              isLoading={isUploading || isCreatingJob}
              disabled={!selectedProduct || files.length === 0}
              icon={!isUploading && !isCreatingJob ? <Plus size={20} /> : undefined}
            >
              {isUploading
                ? 'Uploading Documents...'
                : isCreatingJob
                  ? 'Creating Job...'
                  : 'Create Job'}
            </Button>
          </CardFooter>
        </Card>
      </form>
    </div>
  )
}
