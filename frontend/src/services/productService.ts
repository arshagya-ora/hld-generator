import api from './api'

export interface Product {
  id: string
  name: string
  description: string
  profile_file: string
}

export interface ProductListResponse {
  products: Product[]
  count: number
}

class ProductService {
  async listProducts(): Promise<ProductListResponse> {
    const response = await api.get<ProductListResponse>('/products')
    return response.data
  }

  async getProduct(productId: string): Promise<Product> {
    const response = await api.get<Product>(`/products/${productId}`)
    return response.data
  }
}

export default new ProductService()
