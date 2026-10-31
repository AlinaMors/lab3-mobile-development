import unittest
from mapreduce import mapper
from common import ROLE
class LogicTests(unittest.TestCase):
    def test_unique_skills_and_combinations(self):
        counts,n,ns,m=mapper([('Android разработчик',ROLE,' Kotlin; kotlin; Java; Git; '),('Программист 1С автомобильный бизнес',ROLE,'1C')])
        self.assertEqual((n,ns,m),(1,1,3))
        self.assertEqual([sum(x.values()) for x in counts],[3,3,1])
        self.assertEqual(counts[2][('git','java','kotlin')],1)
    def test_role_and_word_boundaries(self):
        _,n,_,_=mapper([('iOS тестировщик','Тестировщик','iOS'),('BIOS developer',ROLE,'C'),('React Native developer',ROLE,'React Native')])
        self.assertEqual(n,1)
    def test_injected_failure(self):
        with self.assertRaises(RuntimeError):mapper([],True)
if __name__=='__main__':unittest.main()
