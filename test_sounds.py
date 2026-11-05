import unittest
from sound_effects import song_bytes,MELODIES

class SoundTests(unittest.TestCase):
 def test_only_song_bytes_and_valid_note_pairs(self):
  for effect,notes in MELODIES.items():
   data=song_bytes(effect)
   self.assertEqual(data[:3],[140,15,len(notes)])
   self.assertEqual(len(data),3+2*len(notes))
   self.assertTrue(all(31<=pitch<=127 and 1<=duration<=64 for pitch,duration in notes))
 def test_unknown_effect_rejected(self):
  with self.assertRaises(ValueError):song_bytes('arbitrary')
 def test_located_and_arrived_are_distinct(self):
  self.assertNotEqual(song_bytes('located'),song_bytes('finished'))

if __name__=='__main__':unittest.main()
