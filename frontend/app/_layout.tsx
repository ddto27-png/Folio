import { useEffect, useState } from 'react'
import { Stack, router } from 'expo-router'
import { Session } from '@supabase/supabase-js'
import { View, ActivityIndicator } from 'react-native'
import { supabase } from '../lib/supabase'
import { Colors } from '../constants/colors'

export default function RootLayout() {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      setLoading(false)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)
    })
    return () => subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (loading) return
    if (!session) {
      router.replace('/(auth)/sign-in')
    } else {
      checkOnboarding(session.user.id)
    }
  }, [session, loading])

  async function checkOnboarding(userId: string) {
    const { data } = await supabase
      .from('reading_state')
      .select('id')
      .eq('user_id', userId)
      .eq('is_current', true)
      .limit(1)
    router.replace(data && data.length > 0 ? '/(main)/recommendations' : '/onboarding')
  }

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: Colors.background, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={Colors.primary} />
      </View>
    )
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(main)" />
      <Stack.Screen name="onboarding" />
    </Stack>
  )
}
