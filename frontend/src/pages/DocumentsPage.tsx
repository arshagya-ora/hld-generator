import Card from '@/components/ui/Card'
import Button from '@/components/ui/Button'
import { Upload } from 'lucide-react'

export default function DocumentsPage() {
  return (
    <div>
      <h1>Documents</h1>
      <Card>
        <p>Document list and upload will be here</p>
        <Button variant="primary" icon={<Upload size={18} />}>
          Upload Document
        </Button>
      </Card>
    </div>
  )
}
