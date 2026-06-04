// Onboarding is no longer a separate step — books are logged inline on the homepage.
import { redirect } from 'next/navigation'

export default function OnboardingPage() {
  redirect('/')
}
