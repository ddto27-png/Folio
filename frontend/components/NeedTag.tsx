import { View, Text, StyleSheet } from 'react-native'
import { NEED_BY_ID } from '../constants/needs'
import { Colors } from '../constants/colors'

export function NeedTag({ needId }: { needId: number }) {
  const need = NEED_BY_ID[needId]
  if (!need) return null
  return (
    <View style={styles.tag}>
      <Text style={styles.text}>{need.emoji} {need.shortLabel}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  tag: {
    backgroundColor: Colors.tag,
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginRight: 6,
    marginBottom: 6,
  },
  text: {
    color: Colors.tagText,
    fontSize: 12,
    fontWeight: '500',
  },
})
