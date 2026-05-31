import { useEffect, useState, useCallback } from 'react'
import {
  View, Text, FlatList, StyleSheet,
  RefreshControl, SafeAreaView, TouchableOpacity, Alert,
} from 'react-native'
import { router } from 'expo-router'
import { supabase } from '../../lib/supabase'
import { api, Recommendation } from '../../lib/api'
import { BookCard } from '../../components/BookCard'
import { Colors } from '../../constants/colors'

export default function Recommendations() {
  const [books, setBooks] = useState<Recommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [userId, setUserId] = useState<string | null>(null)

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user) {
        setUserId(user.id)
        fetchRecs(user.id)
      }
    })
  }, [])

  async function fetchRecs(uid: string) {
    try {
      const recs = await api.getRecommendations(uid, 10)
      setBooks(recs)
    } catch (e) {
      Alert.alert('Error', 'Could not load recommendations. Is the API running?')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const onRefresh = useCallback(() => {
    if (!userId) return
    setRefreshing(true)
    fetchRecs(userId)
  }, [userId])

  async function saveToWishlist(bookId: string) {
    if (!userId) return
    const { error } = await supabase.from('wishlist').upsert(
      { user_id: userId, book_id: bookId },
      { onConflict: 'user_id,book_id' }
    )
    if (error) Alert.alert('Error', error.message)
    else Alert.alert('Saved', 'Added to your wishlist')
  }

  async function signOut() {
    await supabase.auth.signOut()
    router.replace('/(auth)/sign-in')
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.logo}>Folio</Text>
          <Text style={styles.subtitle}>Picked for you today</Text>
        </View>
        <TouchableOpacity onPress={() => router.push('/onboarding')} style={styles.moodButton}>
          <Text style={styles.moodButtonText}>Update mood</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={books}
        keyExtractor={item => item.book_id}
        renderItem={({ item }) => (
          <BookCard book={item} onSave={saveToWishlist} />
        )}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.primary} />
        }
        ListEmptyComponent={
          !loading ? (
            <View style={styles.empty}>
              <Text style={styles.emptyEmoji}>📚</Text>
              <Text style={styles.emptyText}>
                {books.length === 0
                  ? 'No recommendations yet.\nTry logging some books you\'ve read.'
                  : 'Pull to refresh'}
              </Text>
            </View>
          ) : null
        }
      />
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  logo: { fontSize: 26, fontWeight: '800', color: Colors.primary, letterSpacing: -0.5 },
  subtitle: { fontSize: 13, color: Colors.textMuted, marginTop: 2 },
  moodButton: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: Colors.primary,
  },
  moodButtonText: { color: Colors.primary, fontSize: 13, fontWeight: '600' },
  list: { padding: 16 },
  empty: { alignItems: 'center', paddingTop: 80 },
  emptyEmoji: { fontSize: 48, marginBottom: 16 },
  emptyText: { fontSize: 15, color: Colors.textMuted, textAlign: 'center', lineHeight: 22 },
})
