"""Regression tests for source interpretation, not model performance."""
import unittest
from quota_source_readers import html_grids
from build_expanded_quota_dataset import infer_columns, intake_year, table_headers
from count_public_recommended_rosters import count_rows
from public_quota_urls import public_url


class QuotaReadersTest(unittest.TestCase):
    def test_local_links_blocked(self):
        self.assertEqual(public_url('file:///C:/example.xls'),'')
        self.assertEqual(public_url('http://127.0.0.1/private'),'')

    def test_wechat_session_not_public(self):
        value=public_url('https://mp.weixin.qq.com/s?__biz=example&mid=1&idx=1&sn=public&key=secret&pass_ticket=secret&exportkey=secret')
        self.assertNotIn('secret',value)
        self.assertIn('mid=1',value)

    def test_rowspan(self):
        grids=html_grids('<table><tr><th rowspan="2">学院</th><th colspan="2">人数</th></tr><tr><th>总计划</th><th>推免</th></tr><tr><td>数学学院</td><td>25</td><td>14</td></tr></table>')
        self.assertEqual(grids[0][1],['学院','总计划','推免'])
        self.assertEqual(grids[0][2],['数学学院','25','14'])

    def test_ragged_never_shift(self):
        self.assertEqual(infer_columns(['代码','总计划','推免'],['025200','25'],''),{})

    def test_planned_is_not_actual(self):
        row=infer_columns(['专业代码','拟接收推免人数'],['025200','18'],'已接收推免的考生不得报名')
        self.assertEqual(row,{'planned_recommended':18})

    def test_policy_prose_not_actual(self):
        row=infer_columns(['专业代码','推免人数'],['025200','18'],'已接收推免的考生不得报名')
        self.assertEqual(row,{'unclassified_recommended_count':18})

    def test_actual_notice_bare_column(self):
        row=infer_columns(['专业代码','接收人数'],['025200','3'],'','2024年拟录取硕士推免研究生院系专业统计')
        self.assertEqual(row,{'accepted_recommended':3})

    def test_excluding_recommendation_is_exam_plan(self):
        row=infer_columns(['专业代码','拟招生人数（不含推免）'],['025200','20'],'')
        self.assertEqual(row,{'reported_exam_quota':20})

    def test_including_recommendation_is_total(self):
        row=infer_columns(['专业代码','拟招生人数（含推免）'],['025200','50'],'')
        self.assertEqual(row,{'total_plan_same_scope':50})

    def test_final_admitted_not_visible_plan(self):
        row=infer_columns(['专业代码','统考录取人数'],['025200','13'],'')
        self.assertEqual(row,{'actual_exam_admitted_count':13})

    def test_all_admitted_including_recommendation(self):
        row=infer_columns(['专业代码','录取（含推免）'],['025200','56'],'')
        self.assertEqual(row,{'actual_all_admitted_count':56})

    def test_total_not_overridden_by_post_context(self):
        row=infer_columns(['专业代码','总计划'],['025200','50'],'扣除拟录取推免后的招生计划')
        self.assertEqual(row,{'total_plan_same_scope':50})

    def test_multilevel_header_preferred(self):
        table=[['专业代码','拟招人数','拟招人数'],['专业代码','统考','推免'],['025200','10','20']]
        header=table_headers(table,2)[0]
        self.assertEqual(infer_columns(header,table[2],''),{'reported_exam_quota':10,'planned_recommended':20})

    def test_historical_article_not_current_navigation(self):
        meta={'document_title':'2019年招生计划','title':'2027年导航','url':'https://a.edu.cn/2019/1.html'}
        self.assertIsNone(intake_year(meta,'2027年招生计划导航'))

    def test_score_and_identifier_not_seats(self):
        self.assertEqual(infer_columns(['专业代码','总分','学费','单科线'],['025200','385','1000','60'],''),{})

    def test_unknown_not_zero(self):
        result=count_rows(['专业代码 | 025200 | 应用统计'])
        self.assertIsNone(result['all_modes_count'])

    def test_roster_person_dedup(self):
        rows=['100000000001 | 数学学院 | 025200 | 应用统计 | 全日制',
              '100000000001 | 数学学院 | 025200 | 应用统计 | 全日制',
              '100000000002 | 数学学院 | 025200 | 应用统计 | 非全日制']
        result=count_rows(rows)
        self.assertEqual(result['all_modes_count'],2)
        self.assertEqual(result['explicit_fulltime_count'],1)
        self.assertEqual(result['explicit_nonfulltime_count'],1)

    def test_department_code_not_serial(self):
        self.assertIsNone(count_rows(['007 | 数学学院 | 025200 | 应用统计 | 20'],True)['all_modes_count'])

    def test_mixed_admissions_not_all_recommended(self):
        result=count_rows(['100000000001 | 025200 | 应用统计 | 统考',
                           '100000000002 | 025200 | 应用统计 | 推免'],require_row_recommendation=True)
        self.assertEqual(result['all_modes_count'],1)


if __name__=='__main__':
    unittest.main()
