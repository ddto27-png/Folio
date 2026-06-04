// Recommendations are now on the homepage. Redirect any saved links to "/".
import { redirect } from 'next/navigation'

export default function RecommendationsPage() {
  redirect('/')
}
