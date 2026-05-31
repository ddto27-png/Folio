import { useEffect, useState, useCallback } from 'react'
import {
  View, Text, FlatList, StyleSheet,
  RefreshControl, SafeAreaView, Image, Alert,
} from 'react-native'
import { supabase } from '../../lib/supabase'
import { api, WishlistItem } from '../../lib/api'
import { NeedTag } from '../../components/NeedTag'
import { Colors } from '../../constants/colors'

export default function Wishlist() {
  const [items, setItems] = useState<WishlistItem[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [userId, setUserId] = useState<string | null>(null)

  useEffect(() => {
    supabase.auth.getUser().then(({ data: { user } }) => {
      if (user) {
        setUserId(user.id)
        fetchWishlist(user.id)
      }
    })
  }, [])

  async function fetchWishlist(uid: string) {
    try {
      const data = await api.getWishlist(uid)
      setItems(data)
    } catch (e) {
      Alert.alert('Error', 'Could not load wishlist.')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const onRefresh = useCallback(() => {
    if (!userId) return
    setRefreshing(true)
    fetchWishlist(userId)
  }, [userId])

  function renderItem({ item }: { item: WishlistItem }) {
    const score = item.match_score != null ? Math.round(item.match_score * 100) : null
    return (
      <View style={styles.item}>
        {item.rank != null && (
          <Text style={styles.rank}>#{item.rank}</Text>
        )}
        {item.cover_url ? (
          <Image source={{ uri: item.cover_url }} style={styles.cover} resizeMode="cover" />
        ) : (
          <View style={[styles.cover, styles.coverPlaceholder]}>
            <Text style={{ fontSize: 22 }}>📖</Text>
          </View>
        )}
        <View style={styles.meta}>
          <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
          {item.author && <Text style={styles.author}>{item.author}</Text>}
          {score != null && <Text style={styles.score}>{score}% match</Text>}
          <View style={styles.tags}>
            {(item.need_ids_matched ?? []).map(id => (
              <NeedTag key={id} needId={id} />
            ))}
          </View>
        </View>
      </View>
    )
  }

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.heading}>Wishlist</Text>
        <Text style={styles.subtitle}>Ranked by how well they match you now</Text>
      </View>

      <FlatList
        data={items}
        keyExtractor={item => item.book_id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.primary} />
        }
        ListEmptyComponent={
          !loading ? (
            <View style={styles.empty}>
              <Text style={styles.emptyEmoji}>🔖</Text>
              <Text style={styles.emptyText}>
                No books saved yet.{'\n'}Save books from your recommendations.
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
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 16,
    borderBottomWidth: 1,
    borderBottomColor: Colors.border,
  },
  heading: { fontSize: 26, fontWeight: '800', color: Colors.primary, letterSpacing: -0.5 },
  subtitle: { fontSize: 13, color: Colors.textMuted, marginTop: 2 },
  list: { padding: 16 },
  item: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: Colors.card,
    borderRadius: 14,
    padding: 14,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 6,
    elevation: 1,
  },
  rank: {
    fontSize: 13,
    fontWeight: '700',
    color: Colors.textMuted,
    width: 28,
    paddingTop: 4,
  },
  cover: {
    width: 56,
    height: 84,
    borderRadius: 6,
    marginRight: 12,
  },
  coverPlaceholder: {
    backgroundColor: Colors.tag,
    alignItems: 'center',
    justifyContent: 'center',
  },
  meta: { flex: 1 },
  title: { fontSize: 15, fontWeight: '700', color: Colors.text, marginBottom: 3, lineHeight: 20 },
  author: { fontSize: 12, color: Colors.textMuted, marginBottom: 6 },
  score: { fontSize: 12, color: Colors.primary, fontWeight: '600', marginBottom: 8 },
  tags: { flexDirection: 'row', flexWrap: 'wrap' },
  empty: { alignItems: 'center', paddingTop: 80 },
  emptyEmoji: { fontSize: 48, marginBottom: 16 },
  emptyText: { fontSize: 15, color: Colors.textMuted, textAlign: 'center', lineHeight: 22 },
})
