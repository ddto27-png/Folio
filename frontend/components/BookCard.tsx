import { View, Text, StyleSheet, Image, TouchableOpacity } from 'react-native'
import { Recommendation } from '../lib/api'
import { NeedTag } from './NeedTag'
import { Colors } from '../constants/colors'

interface Props {
  book: Recommendation
  onSave?: (bookId: string) => void
}

export function BookCard({ book, onSave }: Props) {
  const scorePercent = Math.round(book.match_score * 100)

  return (
    <View style={styles.card}>
      <View style={styles.row}>
        {book.cover_url ? (
          <Image source={{ uri: book.cover_url }} style={styles.cover} resizeMode="cover" />
        ) : (
          <View style={[styles.cover, styles.coverPlaceholder]}>
            <Text style={styles.coverPlaceholderText}>📖</Text>
          </View>
        )}

        <View style={styles.meta}>
          <Text style={styles.title} numberOfLines={2}>{book.title}</Text>
          {book.author && <Text style={styles.author}>{book.author}</Text>}

          <View style={styles.scoreRow}>
            <View style={styles.scoreBar}>
              <View style={[styles.scoreFill, { width: `${scorePercent}%` as any }]} />
            </View>
            <Text style={styles.scoreText}>{scorePercent}% match</Text>
          </View>
        </View>
      </View>

      <Text style={styles.whyText}>{book.why_text}</Text>

      <View style={styles.tags}>
        {book.top_need_ids.map(id => <NeedTag key={id} needId={id} />)}
      </View>

      {onSave && (
        <TouchableOpacity style={styles.saveButton} onPress={() => onSave(book.book_id)}>
          <Text style={styles.saveText}>+ Save to wishlist</Text>
        </TouchableOpacity>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.card,
    borderRadius: 16,
    padding: 16,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.06,
    shadowRadius: 8,
    elevation: 2,
  },
  row: {
    flexDirection: 'row',
    marginBottom: 12,
  },
  cover: {
    width: 72,
    height: 108,
    borderRadius: 8,
    marginRight: 14,
  },
  coverPlaceholder: {
    backgroundColor: Colors.tag,
    alignItems: 'center',
    justifyContent: 'center',
  },
  coverPlaceholderText: {
    fontSize: 28,
  },
  meta: {
    flex: 1,
    justifyContent: 'center',
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: Colors.text,
    marginBottom: 4,
    lineHeight: 22,
  },
  author: {
    fontSize: 13,
    color: Colors.textMuted,
    marginBottom: 12,
  },
  scoreRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  scoreBar: {
    flex: 1,
    height: 4,
    backgroundColor: Colors.border,
    borderRadius: 2,
    overflow: 'hidden',
  },
  scoreFill: {
    height: '100%',
    backgroundColor: Colors.primary,
    borderRadius: 2,
  },
  scoreText: {
    fontSize: 12,
    color: Colors.primary,
    fontWeight: '600',
  },
  whyText: {
    fontSize: 14,
    color: Colors.textMuted,
    lineHeight: 20,
    fontStyle: 'italic',
    marginBottom: 12,
  },
  tags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  saveButton: {
    marginTop: 8,
    paddingVertical: 10,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.primary,
    borderRadius: 10,
  },
  saveText: {
    color: Colors.primary,
    fontWeight: '600',
    fontSize: 14,
  },
})
